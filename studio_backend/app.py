"""FastAPI application factory + REST endpoints + WebSocket."""
from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from mimetypes import guess_type

import httpx
from fastapi import FastAPI, File, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from .config import StudioConfig
from .docingest import ingest
from .export import ExportError, export_project
from senza_studio_runtime.contract import describe_agent
from .docs import (
    ingest_cache_path,
    resolve_doc_path,
    safe_document_name,
)
from .play import PlaySession, get_entry_inputs
from .preprocess import PreprocessError, preprocess_spec
from .project import Project, ProjectDataError
from .sdk_pin import check_sdk_pin
from .session import read_session_history
from .storage import atomic_write_bytes, atomic_write_text
from .settings import (
    MODEL_KEYS,
    SETTINGS_SCHEMA,
    SETTINGS_SECTIONS,
    apply_to_environ,
    env_override_values,
    env_overridden_keys,
    load_settings,
    masked_values,
    save_settings,
    snapshot_env_overrides,
)
from .spec import Spec, SpecError
from .agent import StudioAgent
from .agent_team import PROXY_TIMEOUT_SECONDS, install_agent_team_proxy
from .auth import (
    API_COOKIE_NAME,
    http_request_is_authenticated,
    is_valid_api_token,
    token_matches,
    websocket_is_authenticated,
)
from .ws import (
    finalize_play,
    harness_is_busy,
    owner_is_live,
    play_is_active,
    project_lock,
    prompt_is_active,
    run_play_streaming,
    run_prompt_streaming,
    stop_active_prompt,
)


class CreateProjectReq(BaseModel):
    name: str


class UpdateSpecReq(BaseModel):
    spec: dict


class BootstrapAuthReq(BaseModel):
    token: str


MAX_BOOTSTRAP_BODY_BYTES = 1024


async def read_limited_bootstrap_body(request: Request) -> bytes:
    chunks: list[bytes] = []
    total_size = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total_size += len(chunk)
        if total_size > MAX_BOOTSTRAP_BODY_BYTES:
            raise ValueError("Bootstrap request body is too large")
        chunks.append(chunk)
    return b"".join(chunks)


class ExportReq(BaseModel):
    name: str | None = None


class UpdateSettingsReq(BaseModel):
    values: dict


def _open_static_file(
    root: Path, relative_path: str
) -> tuple[int, os.stat_result, Path] | None:
    if not relative_path or "\\" in relative_path or "\x00" in relative_path:
        return None
    segments = relative_path.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        return None
    if any(
        ord(character) < 32 or ord(character) == 127
        for segment in segments
        for character in segment
    ):
        return None
    candidate = root.joinpath(*segments)
    try:
        opened_metadata = candidate.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(opened_metadata.st_mode):
        return None
    try:
        file_descriptor = os.open(
            candidate,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError:
        return None
    try:
        metadata = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_dev != opened_metadata.st_dev
            or metadata.st_ino != opened_metadata.st_ino
        ):
            os.close(file_descriptor)
            return None
    except OSError:
        os.close(file_descriptor)
        return None
    return file_descriptor, metadata, candidate


# ── 全局状态 ──────────────────────────────────────────────
# 活跃项目缓存: {project_id: {"project": Project, "spec": Spec, "agent": StudioAgent}}
_studio_state: dict = {}
_state_load_lock = threading.Lock()


def _reset_state() -> None:
    """清空全局状态（测试用）。"""
    _studio_state.clear()


def _get_or_load_project(config: StudioConfig, project_id: str) -> dict:
    """获取或加载项目到缓存（同步；调用方用 to_thread，避免解析阻塞 loop）。"""
    state = _studio_state.get(project_id)
    if state is not None:
        return state
    with _state_load_lock:
        state = _studio_state.get(project_id)
        if state is not None:
            return state
        project = Project.open(config, project_id)
        spec = project.load_spec()
        agent = StudioAgent(config, project, spec)
        state = {
            "project": project,
            "spec": spec,
            "agent": agent,
            "ws_connections": set(),
            "play_task": None,
            "play_owner": None,
            "play_terminal": None,
            "harness_rebuild_pending": False,
        }
        _studio_state[project_id] = state
        return state


def create_app(config: StudioConfig | None = None) -> FastAPI:
    check_sdk_pin()
    cfg = config or StudioConfig.from_env()
    if not is_valid_api_token(cfg.api_token):
        raise ValueError(
            "Senza Studio API token is required; set "
            "SENZA_STUDIO_API_TOKEN or SENZA_STUDIO_API_TOKEN_FILE"
        )
    static_root = None
    if cfg.static_dir:
        static_root = Path(cfg.static_dir).resolve(strict=True)
        if not static_root.is_dir():
            raise ValueError("Senza Studio static directory is invalid")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.agent_team_client = httpx.AsyncClient(
            timeout=PROXY_TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,
        )
        yield
        await app.state.agent_team_client.aclose()

    app = FastAPI(
        title="Senza Studio",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(ProjectDataError)
    async def project_data_error_handler(request: Request, exc: ProjectDataError):
        # 损坏数据必须显式报错；不要把 500 或空白项目伪装成正常状态。
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.middleware("http")
    async def enforce_local_api_security(request, call_next):
        origin = request.headers.get("origin")
        if origin is not None and origin not in cfg.allowed_origins:
            return JSONResponse(
                status_code=403,
                content={"detail": "Origin is not allowed"},
            )
        if request.url.path not in ("/api/health", "/auth/bootstrap") and not (
            http_request_is_authenticated(request, cfg.api_token)
        ):
            response = JSONResponse(status_code=401, content={"detail": "Not authenticated"})
            response.headers["WWW-Authenticate"] = "Bearer"
            return response
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.allowed_origins),
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    install_agent_team_proxy(
        app,
        cfg.agent_team_descriptor,
        cfg.allowed_origins,
        cfg.api_token,
    )

    # 先快照"哪些设置项来自真正的环境变量"，再注入 settings.json——顺序不
    # 能反，否则注入完就分不清值的来源了（见 settings.snapshot_env_overrides）。
    snapshot_env_overrides()
    _stored_settings = load_settings(cfg)
    apply_to_environ(_stored_settings)

    def _apply_model_settings(stored: dict) -> bool:
        """把 settings.json 里的模型配置写进 cfg，返回是否真的变了。

        必须显式写 cfg 而不是指望 StudioConfig.from_env()：cfg 是在这之前
        就构造好的（要先有 home_dir 才能找到 settings.json），此时再重新
        from_env() 会把测试显式传进来的 config 也一起冲掉。所以只把
        settings.json 的值往 cfg 上盖，且跳过被环境变量接管的项——那些项
        cfg 里已经是环境变量的值了。

        不做这一步的话，"模型"分区看着能存能读，实际完全不起作用：元 agent
        和 Play 读的是 cfg.model / cfg.api_key / cfg.api_base，不是 os.environ。
        """
        overridden = env_overridden_keys()
        field_by_key = {
            "SENZA_STUDIO_MODEL": "model",
            "SENZA_STUDIO_API_BASE": "api_base",
            "SENZA_STUDIO_API_KEY": "api_key",
        }
        changed = False
        for key, field in field_by_key.items():
            if key in overridden:
                continue
            value = stored.get(key)
            if value and getattr(cfg, field) != value:
                setattr(cfg, field, value)
                changed = True
        return changed

    _apply_model_settings(_stored_settings)

    @app.exception_handler(FileNotFoundError)
    async def not_found_handler(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(SpecError)
    async def spec_error_handler(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # ── Health ────────────────────────────────────────────
    @app.get("/api/health")
    async def health():
        return {"status": "ok"}


    # ── Authentication ────────────────────────────────────
    @app.post("/auth/bootstrap")
    async def bootstrap_auth(request: Request):
        try:
            body = await read_limited_bootstrap_body(request)
            req = BootstrapAuthReq.model_validate_json(body)
        except ValueError:
            return JSONResponse(
                status_code=413,
                content={"detail": "Bootstrap request body is too large"},
            )
        except json.JSONDecodeError:
            return JSONResponse(status_code=422, content={"detail": "Invalid JSON"})
        except ValidationError:
            return JSONResponse(status_code=422, content={"detail": "Invalid request"})
        if not token_matches(req.token, cfg.api_token):
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
        response = JSONResponse({"status": "ok"})
        response.set_cookie(
            API_COOKIE_NAME,
            cfg.api_token,
            path="/",
            httponly=True,
            samesite="strict",
        )
        response.headers["Cache-Control"] = "no-store"
        return response


    # ── Settings ─────────────────────────────────────────
    @app.get("/api/settings")
    async def get_settings():
        """schema 给前端渲染表单用；values 里的密钥字段是哨兵而非明文
        （见 settings.masked_values）。"""
        return {
            "schema": SETTINGS_SCHEMA,
            "sections": SETTINGS_SECTIONS,
            "values": masked_values(load_settings(cfg)),
            # 被环境变量接管的项：面板里置灰只读，并显示环境变量的实际值。
            # 不告诉前端的话，用户会看到一个能编辑、存了却不生效的输入框
            # ——这正是"环境变量优先"最容易让人困惑的地方。
            "env_overrides": env_override_values(),
        }

    @app.put("/api/settings")
    async def update_settings(req: UpdateSettingsReq):
        try:
            # 设置文件同样是 fsync 整文件替换，移出事件循环。
            saved = await asyncio.to_thread(save_settings, cfg, req.values)
        except Exception as exc:  # noqa: BLE001
            # 损坏文件已隔离；明确告诉用户原始字节在哪、需要重新保存。
            return JSONResponse(
                status_code=500,
                content={"detail": f"设置保存失败：{exc}"},
            )
        apply_to_environ(saved)
        # 模型配置变了要重建已经建好的 harness：provider 和 model 是
        # HarnessBuilder build 时定死的，只改 cfg 不重建的话，当前打开的
        # 项目还会继续用旧模型，直到用户重启后端或切项目——跟改 spec 之后
        # 调 agent.rebuild() 是同一个道理（见 update_spec）。
        warnings: list[str] = []
        if _apply_model_settings(saved):
            for project_id, state in list(_studio_state.items()):
                agent = state.get("agent")
                if agent is None or agent._session_id is None:
                    continue
                if harness_is_busy(state):
                    # 绝不替换正在被 Prompt/Play 使用的 harness；记录 pending，
                    # 由 finalizer 或下一次安全启动点应用最新设置。
                    state["harness_rebuild_pending"] = True
                    warnings.append(f"项目 {project_id} 正在运行，模型设置将在本轮结束后应用")
                    continue
                try:
                    async with project_lock(state):
                        await asyncio.to_thread(agent.rebuild)
                    state.pop("harness_rebuild_pending", None)
                except Exception as exc:  # noqa: BLE001
                    # 重建失败（比如 key 填错了）不该让保存这个动作失败
                    # ——设置已经写盘了，下次用到时还会再试一次。
                    state["harness_rebuild_pending"] = True
                    warnings.append(f"项目 {project_id} 重建失败：{exc}")
                    print(f"agent rebuild after settings change failed: {exc}",
                          file=sys.stderr)
        return {
            "status": "ok",
            "values": masked_values(saved),
            "env_overrides": env_override_values(),
            "warnings": warnings,
        }

    # ── Projects ─────────────────────────────────────────
    @app.get("/api/projects")
    async def list_projects():
        return await asyncio.to_thread(Project.list_all, cfg)

    @app.post("/api/projects")
    async def create_project(req: CreateProjectReq):
        proj = await asyncio.to_thread(Project.create, cfg, req.name)
        return {"id": proj.meta["id"], "name": proj.meta["name"]}

    @app.get("/api/projects/{project_id}")
    async def get_project(project_id: str):
        state = await asyncio.to_thread(_get_or_load_project, cfg, project_id)
        return state["project"].meta

    @app.delete("/api/projects/{project_id}")
    async def delete_project(project_id: str):
        state = _studio_state.get(project_id)
        if state is not None:
            if prompt_is_active(state) or play_is_active(state):
                return JSONResponse(
                    status_code=409,
                    content={"detail": "项目正在运行，请先停止再删除"},
                )
            _studio_state.pop(project_id, None)
        await asyncio.to_thread(Project.delete, cfg, project_id)
        return {"status": "ok"}

    # ── Spec ─────────────────────────────────────────────
    @app.get("/api/projects/{project_id}/spec")
    async def get_spec(project_id: str):
        state = await asyncio.to_thread(_get_or_load_project, cfg, project_id)
        return state["spec"].get_current_spec()

    # 25MB：够放常见的表格/PDF，又不至于让一份误传的视频把内存和磁盘吃满。
    MAX_UPLOAD_BYTES = 25 * 1024 * 1024

    @app.post("/api/projects/{project_id}/documents")
    async def upload_document(project_id: str, file: UploadFile = File(...)):
        """上传文档：存原文 → 立刻解析 → 缓存摘要 → 重建 harness。

        为什么上传完要 rebuild：system prompt 是在 _build_harness() 时定死的
        （agent.py），文档清单属于它的动态段。不重建的话新上传的文件要等到下次
        建 harness 才进得了模型视野，用户传完接着问"照这个建流程"会得到一句
        "我看不到任何文档"。跟 update_spec 改完 spec 之后 rebuild 是同一个套路。
        """
        state = await asyncio.to_thread(_get_or_load_project, cfg, project_id)
        project = state["project"]

        name = safe_document_name(file.filename or "")
        path = resolve_doc_path(project, name or "")
        if name is None or path is None:
            return JSONResponse(
                status_code=400,
                content={"detail": f"文件名不合法：{file.filename!r}"},
            )

        # 边读边计数，不先整个读进内存——25MB 的限制要在读的过程中就生效，
        # 否则一个 2GB 的文件在检查之前就已经把内存吃掉了。
        size = 0
        chunks: list[bytes] = []
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限"
                    },
                )
            chunks.append(chunk)
        if size == 0:
            return JSONResponse(status_code=400, content={"detail": "文件是空的"})

        payload = b"".join(chunks)

        def _store_document() -> dict:
            # 原文是用户数据；不能用直接 write 留下 0 字节/半文件。
            atomic_write_bytes(path, payload)
            result = ingest(path)
            cache = ingest_cache_path(project, name)
            atomic_write_text(
                cache,
                json.dumps(result, ensure_ascii=False, default=str),
            )
            return result

        async with project_lock(state):
            # 写文件 + 文档解析都可能重；不能占住事件循环。
            result = await asyncio.to_thread(_store_document)

        applied = True
        warning: str | None = None
        agent = state.get("agent")
        if agent is not None and agent._session_id is not None:
            if harness_is_busy(state):
                # 文档已经安全落盘；绝不在 Prompt/Play 使用 harness 时替换。
                state["harness_rebuild_pending"] = True
                applied = False
                warning = "文档已保存；本轮运行结束后会更新 harness。"
            else:
                try:
                    async with project_lock(state):
                        await asyncio.to_thread(agent.rebuild)
                    state.pop("harness_rebuild_pending", None)
                except Exception as exc:  # noqa: BLE001
                    # 文件已经存好了，重建失败不该让上传显示为失败——下次建
                    # harness 时还会再读一遍。
                    state["harness_rebuild_pending"] = True
                    applied = False
                    warning = f"文档已保存，但 harness 重建失败：{exc}"
                    print(f"agent rebuild after upload failed: {exc}", file=sys.stderr)

        return {
            "name": name,
            "kind": result.get("kind"),
            "summary": result.get("summary"),
            # 解析失败也返回 200：文件确实存下来了，失败的是解析。前端据此
            # 显示一条说明，而不是把上传本身报成错误。
            "ok": result.get("kind") != "error",
            "applied": applied,
            "warning": warning,
        }

    # Agent 界面的构建产物（studio_frontend/agent/ → dist-agent/）。**不是**
    # Studio 自己的 dist：导出的是做好的 agent，不是做它用的编辑器，DAG /
    # Inspector / Play 控制条不该出现在交付物里。两者是两次独立的 vite
    # build，所以编辑器的代码根本没打进导出包。
    # dev 模式下可能还没 build 过，那就导出一个没有网页界面的项目，并在
    # 响应里说明。
    WEBUI_DIST = Path(__file__).resolve().parent.parent / "studio_frontend" / "dist-agent"

    @app.post("/api/projects/{project_id}/export")
    async def export_project_endpoint(project_id: str, req: ExportReq):
        """导出成可独立运行的项目目录。

        用内存里的 spec 而不是 pipeline.yaml：用户要导出的是他现在屏幕上那份。
        """
        state = await asyncio.to_thread(_get_or_load_project, cfg, project_id)
        try:
            # export 内部会 copytree + 同步调用 pip wheel（单包最长 180s）。
            # 留在事件循环里会冻结所有 WS/REST；放到工作线程，循环继续服务。
            target, with_webui, missing_wheels = await asyncio.to_thread(
                export_project,
                state["project"],
                state["spec"],
                name=req.name,
                webui_dist=WEBUI_DIST,
            )
        except ExportError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})
        notes: list[str] = []
        if not with_webui:
            # 没带上前端不是失败，但用户得知道——否则跑起来看到的是空页面
            notes.append(
                "没有找到 Agent 界面的构建产物，导出的项目暂时没有网页界面。"
                "在 studio_frontend/ 里跑一次 npm run build 再导出即可。"
            )
        if missing_wheels:
            # 同理：目录还是能用，只是不能整个拷给别人直接装
            notes.append(
                "这几个依赖没能打进 vendor/：" + "、".join(missing_wheels)
                + "。导出的项目需要自己解决它们才能安装。"
            )
        return {
            "path": str(target),
            "with_webui": with_webui,
            "missing_wheels": missing_wheels,
            "note": "\n".join(notes) or None,
        }

    @app.get("/api/projects/{project_id}/agent")
    async def get_agent_contract(project_id: str):
        """Game view 的渲染契约——和导出 Agent 的 GET /api/agent 完全同构，
        由同一个 describe_agent 生成。

        Game view 就是导出产品的预览，所以它不该自己去翻 spec 算 ui.display /
        审批选项/标签：那等于把同一套规则实现两遍，两份实现迟早不一样（已经
        踩过一次）。画布要的那份结构信息走 expanded_spec，和这里井水不犯河水。
        """
        state = await asyncio.to_thread(_get_or_load_project, cfg, project_id)
        return describe_agent(
            state["spec"].get_current_spec(),
            str(state["project"].meta.get("name") or "Agent"),
        )

    @app.get("/api/projects/{project_id}/expanded_spec")
    async def get_expanded_spec(project_id: str):
        """展开能力组件之后的 spec——画布画组件 group 用。

        画布不能只靠 Play 时下发的 runtime_spec：编辑态也要能展开组件看内部
        step（这正是 Phase 4 的验收标准之一），而编辑的时候根本没在跑。

        展开失败不返回 4xx：spec 写坏是编辑过程中的常态（组件名还没填完、
        参数写了一半），画布该退回去画未展开的引用形态并把原因显示出来，
        而不是整块报错。所以错误放在 error 字段里，spec 给 null。
        """
        state = await asyncio.to_thread(_get_or_load_project, cfg, project_id)
        try:
            return {
                "spec": preprocess_spec(state["spec"].get_current_spec()),
                "error": None,
            }
        except PreprocessError as exc:
            return {"spec": None, "error": str(exc)}

    @app.put("/api/projects/{project_id}/spec")
    async def update_spec(project_id: str, req: UpdateSpecReq):
        state = await asyncio.to_thread(_get_or_load_project, cfg, project_id)
        new_spec = Spec(req.spec)
        try:
            new_spec.validate()
        except SpecError as e:
            return JSONResponse(status_code=400, content={"detail": str(e)})

        if harness_is_busy(state):
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "prompt/Play 运行期间不能替换 spec；请等待结束后再保存。",
                    "saved": False,
                    "applied": False,
                },
            )

        # 先落盘，成功后才换内存/重建。否则保存失败时 GET /spec 会返回
        # 一个“看起来已保存”的新 spec，用户重试还会覆盖旧内容。
        try:
            async with project_lock(state):
                await asyncio.to_thread(state["project"].save_spec, new_spec)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                status_code=500,
                content={
                    "detail": f"spec 保存失败：{exc}",
                    "saved": False,
                    "applied": False,
                },
            )

        state["spec"] = new_spec
        state["agent"]._spec = new_spec
        applied = True
        warning: str | None = None
        if state["agent"]._session_id is not None:
            try:
                async with project_lock(state):
                    await asyncio.to_thread(state["agent"].rebuild)
                state.pop("harness_rebuild_pending", None)
            except Exception as exc:  # noqa: BLE001
                # 磁盘已提交，但当前 harness 还是旧的。必须区分“已保存”
                # 和“运行时未成功应用”，不能整体报成保存失败。
                state["harness_rebuild_pending"] = True
                applied = False
                warning = f"spec 已保存，但运行时重建失败：{exc}"
                print(f"agent rebuild after spec save failed: {exc}", file=sys.stderr)
        return {
            "status": "ok",
            "saved": True,
            "applied": applied,
            "warning": warning,
        }

    # ── Sessions ─────────────────────────────────────────
    @app.get("/api/projects/{project_id}/sessions")
    async def list_sessions(project_id: str):
        state = await asyncio.to_thread(_get_or_load_project, cfg, project_id)
        return {
            "sessions": state["project"].meta.get("sessions", []),
            "active": state["project"].meta.get("active_session"),
        }

    @app.post("/api/projects/{project_id}/sessions")
    async def create_session(project_id: str):
        state = await asyncio.to_thread(_get_or_load_project, cfg, project_id)
        async with project_lock(state):
            sid = await asyncio.to_thread(state["project"].create_session)
        return {"session_id": sid}

    @app.get("/api/projects/{project_id}/messages")
    async def get_messages(project_id: str):
        state = await asyncio.to_thread(_get_or_load_project, cfg, project_id)
        project = state["project"]
        active = project.meta.get("active_session")
        if not active:
            return []
        try:
            return await asyncio.to_thread(
                read_session_history, project.sessions_dir, active
            )
        except (ValueError, RuntimeError) as exc:
            return JSONResponse(
                status_code=422,
                content={"detail": f"active session 无法安全恢复：{exc}"},
            )

    # ── Play ───────────────────────────────────────────────
    @app.get("/api/projects/{project_id}/entry_inputs")
    async def entry_inputs(project_id: str):
        state = await asyncio.to_thread(_get_or_load_project, cfg, project_id)
        return {"fields": get_entry_inputs(state["spec"].get_current_spec())}

    # ── WebSocket ────────────────────────────────────────
    @app.websocket("/ws/projects/{project_id}")
    async def project_ws(websocket: WebSocket, project_id: str):
        origin = websocket.headers.get("origin")
        if origin is not None and origin not in cfg.allowed_origins:
            await websocket.close(code=1008)
            return
        if not websocket_is_authenticated(websocket, cfg.api_token):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            state = await asyncio.to_thread(_get_or_load_project, cfg, project_id)
        except ProjectDataError as exc:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"项目数据损坏，无法加载：{exc}",
                    "source": "project",
                    "terminal": True,
                }
            )
            await websocket.close(code=1011)
            return
        agent = state["agent"]
        project = state["project"]
        # 每条 WS 连接一个稳定标识：prompt 抢占/abort 只允许发起它的连接操作，
        # 另一个 tab 不能误杀正在运行的 run。
        connection_id = f"ws-{uuid.uuid4().hex}"

        # 如果 agent 还没启动 session，启动一个。session 持久化不可用时
        # 必须让用户看到原因，不能带着内存会话继续跑。
        if agent._harness is None:
            active = project.meta.get("active_session")
            try:
                async with project_lock(state):
                    # 两条连接可能同时看到 _harness is None；拿到锁后必须
                    # 再查一次，避免第二条连接无谓重建刚建好的 harness。
                    if agent._harness is None:
                        await asyncio.to_thread(agent.start_session, active)
            except Exception as exc:  # noqa: BLE001
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"无法启动会话：{exc}",
                        "source": "session",
                        "terminal": True,
                    }
                )
                await websocket.close(code=1011)
                return

        # 在线连接集合用于判断 prompt/play owner 是否还活着。只有 owner
        # 不在集合里（连接已断开）时，重连连接才允许接管。
        connections = state.setdefault("ws_connections", set())
        connections.add(connection_id)

        # 登记当前活跃 socket——prompt 终态推送（跨 run）以此为投递目标。
        # 旧连接被新连接替换时自动覆盖；断开时清空由 finally 完成。
        state["ws_socket"] = websocket
        # 重连对账：把当前/最近一次 prompt run 的状态推给新连接。
        run = state.get("prompt_run")
        if run is not None:
            try:
                await websocket.send_json({"type": "prompt_state", "run": dict(run)})
            except Exception:
                pass

        play_task: asyncio.Task | None = None

        try:
            while True:
                msg = await websocket.receive_json()
                msg_type = msg.get("type")

                if msg_type in ("submit_decision", "pause", "resume", "step"):
                    owner = state.get("play_owner")
                    if (
                        play_is_active(state)
                        and owner != connection_id
                        and owner_is_live(state, owner)
                    ):
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": "另一个连接正在控制 Play；当前连接无权操作。",
                                "source": "play",
                            }
                        )
                        continue

                if msg_type == "play":
                    existing = state.get("play_task")
                    if existing is not None and not existing.done():
                        owner = state.get("play_owner")
                        if owner != connection_id and owner_is_live(state, owner):
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "message": "另一个连接正在运行 Play；不能从当前连接启动。",
                                    "source": "play",
                                }
                            )
                            continue
                        if owner != connection_id:
                            # 原连接已断开：先停掉孤儿 run，再允许重连接管。
                            old_session = state.get("play_session")
                            if old_session is not None:
                                old_session.stop("connection closed")
                            existing.cancel()
                            try:
                                await existing
                            except asyncio.CancelledError:
                                pass
                        else:
                            continue  # 同连接重复 play，幂等忽略
                    play_session = PlaySession(cfg, project, state["spec"])
                    state["play_session"] = play_session
                    try:
                        async with project_lock(state):
                            await asyncio.to_thread(
                                play_session.play,
                                inputs=msg.get("inputs"),
                                start_paused=bool(msg.get("start_paused")),
                            )
                    except Exception as exc:  # noqa: BLE001
                        # 构建阶段就失败了（最常见的是能力组件展开出错：引用
                        # 了不存在的组件、参数写错、出口名写错）。不接住的话
                        # 异常会一路穿出 WS handler 把连接打死——前端点了 Play
                        # 已经乐观地切到 playing 状态，看到的就是"界面卡在运行
                        # 中 + 连接莫名断开"，完全看不出哪里错了（亲测）。
                        #
                        # 这条 error 故意不带 source: "play"：run 压根没开始，
                        # 前端就该退回 spec_ready 去改 spec，而不是留在 Play
                        # 视图里等一个永远不会来的结果。
                        state["play_session"] = None
                        failure = {"type": "error", "message": f"无法启动 Play: {exc}"}
                        # Conversation sessions retain history and allow retry even
                        # when construction fails before the first step event.
                        if state["spec"].get_current_spec().get("ui", {}).get("layout") == "conversation":
                            failure["source"] = "play"
                            failure["terminal"] = True
                        await websocket.send_json(failure)
                        continue
                    state["play_owner"] = connection_id
                    state["play_terminal"] = None
                    play_task = asyncio.create_task(
                        run_play_streaming(websocket, play_session, project, state)
                    )
                    state["play_task"] = play_task

                    def _clear_play_task(
                        task: asyncio.Task,
                        session=play_session,
                        owner=connection_id,
                    ) -> None:
                        if state.get("play_task") is not task:
                            return
                        state.pop("play_task", None)
                        # 下一次 Play 可能已在 to_thread(play()) 里、尚未替换
                        # play_task；此时 state["play_session"] 已是新对象。
                        # 只清本 task 对应的 session/owner，不能误清新 run。
                        if state.get("play_session") is session:
                            state.pop("play_session", None)
                        if state.get("play_owner") == owner:
                            state.pop("play_owner", None)
                        try:
                            task.result()
                            status = "completed"
                        except asyncio.CancelledError:
                            status = "cancelled"
                        except Exception as exc:  # noqa: BLE001
                            status = "failed"
                            print(f"Play task error: {exc}", file=sys.stderr)
                        state["play_terminal"] = {
                            "status": status,
                            "ended_at": time.time(),
                        }

                    play_task.add_done_callback(_clear_play_task)

                elif msg_type == "stop":
                    play_task = state.get("play_task")
                    owner = state.get("play_owner")
                    if (
                        play_is_active(state)
                        and owner != connection_id
                        and owner_is_live(state, owner)
                    ):
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": "另一个连接正在运行 Play；不能从当前连接停止。",
                                "source": "play",
                            }
                        )
                        continue
                    play_session = state.get("play_session")
                    if play_session is not None:
                        play_session.stop("user stop")
                    if play_task is not None and not play_task.done():
                        try:
                            await play_task
                        except asyncio.CancelledError:
                            pass
                    # 无论 play_task 是刚被 Stop、已经自然结束，还是刚好在线程
                    # 死亡与事件流退出之间的窗口，都把项目收尾回 editing。
                    # finalize_play 自身幂等，重复调用无害。
                    await finalize_play(websocket, project, state)

                elif msg_type == "submit_decision":
                    # checker step 在等人工审批——run_play_streaming 的事件
                    # 循环在 paused 状态下不会退出（见 ws.py 里的注释），
                    # 同一个 subscribe() 订阅在 submit_decision() 重新
                    # run() 之后还能继续收到事件，不需要另起 play_task。
                    play_session = state.get("play_session")
                    if play_session is not None:
                        step_id = msg.get("step_id")
                        decision = msg.get("decision")
                        if step_id and decision:
                            play_session.submit_decision(step_id, decision)

                elif msg_type == "pause":
                    play_session = state.get("play_session")
                    if play_session is not None:
                        play_session.request_pause()

                elif msg_type == "resume":
                    # 跟 submit_decision 同一个道理——run_play_streaming 的
                    # 事件循环在 paused 状态下不会退出，同一个 subscribe()
                    # 订阅在 resume_run() 重新 run() 之后还能继续收到事件，
                    # 不需要另起 play_task。
                    play_session = state.get("play_session")
                    if play_session is not None:
                        play_session.resume_run()

                elif msg_type == "step":
                    play_session = state.get("play_session")
                    if play_session is not None:
                        play_session.step()

                elif msg_type == "prompt":
                    # 同项目必须串行：同连接可 abort + 有界等待旧 run；跨连接
                    # 直接拒绝，避免两个 tab 共用同一个 harness/线程。
                    stop_error = await stop_active_prompt(state, agent, connection_id)
                    if stop_error is not None:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": stop_error,
                                "source": "prompt",
                            }
                        )
                        continue

                    if state.get("harness_rebuild_pending"):
                        if play_is_active(state):
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "message": "Play 运行中，模型/文档设置尚未应用；请先停止 Play 或等待结束。",
                                    "source": "prompt",
                                }
                            )
                            continue
                        try:
                            async with project_lock(state):
                                await asyncio.to_thread(agent.rebuild)
                            state.pop("harness_rebuild_pending", None)
                        except Exception as exc:  # noqa: BLE001
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "message": f"应用待生效的设置失败：{exc}",
                                    "source": "prompt",
                                }
                            )
                            continue

                    text = msg.get("text", "")
                    # 客户端生成的 run id——终态行的关联/去重键。缺失时退化
                    # 为后端生成（旧客户端兼容），不阻塞本次执行。
                    run_id = msg.get("run_id")
                    if not isinstance(run_id, str) or not run_id:
                        run_id = f"srv-{int(time.time() * 1000)}"
                    state["prompt_run"] = {
                        "run_id": run_id,
                        "prompt": text,
                        "status": "running",
                        "error": None,
                        "started_at": time.time(),
                        "ended_at": None,
                        # 连接归属：别的 tab 不能 abort/抢占本 run。
                        "owner": connection_id,
                    }
                    # run 所有权放在项目 state，而不是 handler 局部变量：
                    # 连接断开后任务继续执行，重连/另一个连接可据此对账。
                    prompt_task = asyncio.create_task(
                        run_prompt_streaming(
                            websocket,
                            agent,
                            project,
                            text,
                            state,
                            run_id,
                            cancel_driver_on_timeout=True,
                        )
                    )
                    state["prompt_task"] = prompt_task

                    def _clear_prompt_task(task: asyncio.Task) -> None:
                        if state.get("prompt_task") is task:
                            state.pop("prompt_task", None)

                    prompt_task.add_done_callback(_clear_prompt_task)

                elif msg_type == "abort":
                    run = state.get("prompt_run")
                    owner = run.get("owner") if isinstance(run, dict) else None
                    if (
                        isinstance(run, dict)
                        and run.get("status") == "running"
                        and owner not in (None, connection_id)
                        and owner_is_live(state, owner)
                    ):
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": "另一个连接正在运行 prompt；不能从当前连接中止。",
                                "source": "prompt",
                            }
                        )
                    else:
                        # owner 已断线时，重连连接可以中止这个孤儿 run。
                        agent.abort()

                elif msg_type == "switch_session":
                    sid = msg.get("session_id")
                    if harness_is_busy(state):
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": "prompt/Play 运行期间不能切换 session；请先等待结束或停止。",
                                "source": "prompt",
                            }
                        )
                        continue
                    if sid:
                        try:
                            async with project_lock(state):
                                await asyncio.to_thread(agent.start_session, sid)
                            state.pop("harness_rebuild_pending", None)
                        except Exception as exc:  # noqa: BLE001
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "message": f"切换会话失败：{exc}",
                                    "source": "session",
                                }
                            )
                            continue
                        await websocket.send_json(
                            {
                                "type": "session_switched",
                                "session_id": sid,
                            }
                        )

        except WebSocketDisconnect:
            pass
        finally:
            state.setdefault("ws_connections", set()).discard(connection_id)
            # 只释放本 handler 登记的 socket。A 断开后若 B 已重连并
            # 覆盖了该槽位，A 的延迟 cleanup 不得清掉 B。prompt 收尾
            # 仍会在发送时重新读取该槽位，所以之后接管的 B 仍能收到终态。
            if state.get("ws_socket") is websocket:
                state["ws_socket"] = None
            # prompt 任务的所有权在 state 上：断线只清 socket 槽，绝不 cancel
            # 正在执行的 run。终态收尾由独立的 finalizer 继续完成。
            play_task = state.get("play_task")
            if (
                play_task is not None
                and not play_task.done()
                and state.get("play_owner") == connection_id
            ):
                play_session = state.get("play_session")
                if play_session is not None:
                    play_session.stop("connection closed")
                play_task.cancel()
                try:
                    await play_task
                except asyncio.CancelledError:
                    pass
            # 断线也走统一收尾：自然结束窗口、取消路径、Stop 后残留都不能
            # 让 meta 永久停在 playing。不能收掉另一个仍在线连接拥有的 Play。
            if not play_is_active(state) or state.get("play_owner") == connection_id:
                await finalize_play(websocket, project, state)

    if static_root is not None:
        @app.get("/{full_path:path}")
        async def serve_static_file(full_path: str):
            opened_file = _open_static_file(
                static_root, full_path if full_path else "index.html"
            )
            if opened_file is None:
                return JSONResponse(status_code=404, content={"detail": "Not found"})
            file_descriptor, metadata, file_path = opened_file
            media_type = guess_type(file_path.name)[0] or "application/octet-stream"
            headers = {
                "Cache-Control": "no-store",
                "Content-Length": str(metadata.st_size),
            }
            if file_path.relative_to(static_root).parts[0] == "assets":
                headers["Cache-Control"] = "public, max-age=31536000, immutable"

            def static_file_chunks():
                with os.fdopen(file_descriptor, "rb") as static_file:
                    while chunk := static_file.read(64 * 1024):
                        yield chunk

            return StreamingResponse(
                static_file_chunks(),
                media_type=media_type,
                headers=headers,
            )


    return app
