"""FastAPI application factory + REST endpoints + WebSocket."""
from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import StudioConfig
from .play import PlaySession, get_entry_inputs
from .preprocess import PreprocessError, preprocess_spec
from .project import Project
from .sdk_pin import check_sdk_pin
from .session import read_session_history
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
from .ws import finalize_play, run_play_streaming, run_prompt_streaming


class CreateProjectReq(BaseModel):
    name: str


class UpdateSpecReq(BaseModel):
    spec: dict


class UpdateSettingsReq(BaseModel):
    values: dict


# ── 全局状态 ──────────────────────────────────────────────
# 活跃项目缓存: {project_id: {"project": Project, "spec": Spec, "agent": StudioAgent}}
_studio_state: dict = {}


def _reset_state() -> None:
    """清空全局状态（测试用）。"""
    _studio_state.clear()


def _get_or_load_project(config: StudioConfig, project_id: str) -> dict:
    """获取或加载项目到缓存。"""
    if project_id not in _studio_state:
        project = Project.open(config, project_id)
        spec = project.load_spec()
        agent = StudioAgent(config, project, spec)
        _studio_state[project_id] = {
            "project": project,
            "spec": spec,
            "agent": agent,
        }
    return _studio_state[project_id]


def create_app(config: StudioConfig | None = None) -> FastAPI:
    check_sdk_pin()
    cfg = config or StudioConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.agent_team_client = httpx.AsyncClient(
            timeout=PROXY_TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,
        )
        yield
        await app.state.agent_team_client.aclose()

    app = FastAPI(title="Senza Studio", lifespan=lifespan)

    @app.middleware("http")
    async def reject_foreign_origin(request, call_next):
        origin = request.headers.get("origin")
        if origin is not None and origin not in cfg.allowed_origins:
            return JSONResponse(
                status_code=403,
                content={"detail": "Origin is not allowed"},
            )
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.allowed_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    install_agent_team_proxy(
        app,
        cfg.agent_team_descriptor,
        cfg.allowed_origins,
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
        saved = save_settings(cfg, req.values)
        apply_to_environ(saved)
        # 模型配置变了要重建已经建好的 harness：provider 和 model 是
        # HarnessBuilder build 时定死的，只改 cfg 不重建的话，当前打开的
        # 项目还会继续用旧模型，直到用户重启后端或切项目——跟改 spec 之后
        # 调 agent.rebuild() 是同一个道理（见 update_spec）。
        if _apply_model_settings(saved):
            for state in _studio_state.values():
                agent = state.get("agent")
                if agent is not None and agent._session_id is not None:
                    try:
                        agent.rebuild()
                    except Exception as exc:  # noqa: BLE001
                        # 重建失败（比如 key 填错了）不该让保存这个动作失败
                        # ——设置已经写盘了，下次用到时还会再试一次。
                        print(f"agent rebuild after settings change failed: {exc}",
                              file=sys.stderr)
        return {
            "status": "ok",
            "values": masked_values(saved),
            "env_overrides": env_override_values(),
        }

    # ── Projects ─────────────────────────────────────────
    @app.get("/api/projects")
    async def list_projects():
        return Project.list_all(cfg)

    @app.post("/api/projects")
    async def create_project(req: CreateProjectReq):
        proj = Project.create(cfg, req.name)
        return {"id": proj.meta["id"], "name": proj.meta["name"]}

    @app.get("/api/projects/{project_id}")
    async def get_project(project_id: str):
        state = _get_or_load_project(cfg, project_id)
        return state["project"].meta

    @app.delete("/api/projects/{project_id}")
    async def delete_project(project_id: str):
        state = _studio_state.get(project_id)
        if state is not None:
            play_session = state.get("play_session")
            if play_session is not None and play_session.state() in (
                "running",
                "paused",
            ):
                return JSONResponse(
                    status_code=409,
                    content={"detail": "项目正在运行，请先停止再删除"},
                )
            _studio_state.pop(project_id, None)
        Project.delete(cfg, project_id)
        return {"status": "ok"}

    # ── Spec ─────────────────────────────────────────────
    @app.get("/api/projects/{project_id}/spec")
    async def get_spec(project_id: str):
        state = _get_or_load_project(cfg, project_id)
        return state["spec"].get_current_spec()

    @app.get("/api/projects/{project_id}/expanded_spec")
    async def get_expanded_spec(project_id: str):
        """展开能力组件之后的 spec——画布画组件 group 用。

        画布不能只靠 Play 时下发的 runtime_spec：编辑态也要能展开组件看内部
        step（这正是 Phase 4 的验收标准之一），而编辑的时候根本没在跑。

        展开失败不返回 4xx：spec 写坏是编辑过程中的常态（组件名还没填完、
        参数写了一半），画布该退回去画未展开的引用形态并把原因显示出来，
        而不是整块报错。所以错误放在 error 字段里，spec 给 null。
        """
        state = _get_or_load_project(cfg, project_id)
        try:
            return {
                "spec": preprocess_spec(state["spec"].get_current_spec()),
                "error": None,
            }
        except PreprocessError as exc:
            return {"spec": None, "error": str(exc)}

    @app.put("/api/projects/{project_id}/spec")
    async def update_spec(project_id: str, req: UpdateSpecReq):
        state = _get_or_load_project(cfg, project_id)
        # 替换 spec 内容
        new_spec = Spec(req.spec)
        try:
            new_spec.validate()
        except SpecError as e:
            return JSONResponse(status_code=400, content={"detail": str(e)})
        state["spec"] = new_spec
        state["agent"]._spec = new_spec
        state["project"].save_spec(new_spec)
        # 重建 agent（system prompt 需更新）
        if state["agent"]._session_id is not None:
            state["agent"].rebuild()
        return {"status": "ok"}

    # ── Sessions ─────────────────────────────────────────
    @app.get("/api/projects/{project_id}/sessions")
    async def list_sessions(project_id: str):
        state = _get_or_load_project(cfg, project_id)
        return {
            "sessions": state["project"].meta.get("sessions", []),
            "active": state["project"].meta.get("active_session"),
        }

    @app.post("/api/projects/{project_id}/sessions")
    async def create_session(project_id: str):
        state = _get_or_load_project(cfg, project_id)
        sid = state["project"].create_session()
        return {"session_id": sid}

    @app.get("/api/projects/{project_id}/messages")
    async def get_messages(project_id: str):
        state = _get_or_load_project(cfg, project_id)
        project = state["project"]
        active = project.meta.get("active_session")
        if not active:
            return []
        return read_session_history(project.sessions_dir, active)

    # ── Play ───────────────────────────────────────────────
    @app.get("/api/projects/{project_id}/entry_inputs")
    async def entry_inputs(project_id: str):
        state = _get_or_load_project(cfg, project_id)
        return {"fields": get_entry_inputs(state["spec"].get_current_spec())}

    # ── WebSocket ────────────────────────────────────────
    @app.websocket("/ws/projects/{project_id}")
    async def project_ws(websocket: WebSocket, project_id: str):
        await websocket.accept()
        state = _get_or_load_project(cfg, project_id)
        agent = state["agent"]
        project = state["project"]

        # 如果 agent 还没启动 session，启动一个
        if agent._harness is None:
            active = project.meta.get("active_session")
            agent.start_session(active)

        streaming_task: asyncio.Task | None = None
        play_task: asyncio.Task | None = None

        try:
            while True:
                msg = await websocket.receive_json()
                msg_type = msg.get("type")

                if msg_type == "play":
                    if play_task is not None and not play_task.done():
                        continue  # 已经在跑，忽略重复 play
                    play_session = PlaySession(cfg, project, state["spec"])
                    state["play_session"] = play_session
                    try:
                        play_session.play(
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
                        await websocket.send_json(
                            {"type": "error", "message": f"无法启动 Play: {exc}"}
                        )
                        continue
                    play_task = asyncio.create_task(
                        run_play_streaming(websocket, play_session, project)
                    )

                elif msg_type == "stop":
                    play_session = state.get("play_session")
                    if play_session is not None:
                        play_session.stop("user stop")
                    if play_task is not None and not play_task.done():
                        try:
                            await play_task
                        except asyncio.CancelledError:
                            pass
                    else:
                        # 运行已经自然结束（succeeded/failed），run_play_streaming
                        # 早就退出了，得在这里自己收尾回 editing。
                        await finalize_play(websocket, project)

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
                    # 如果上一个 prompt 还在跑，先中止
                    if streaming_task is not None and not streaming_task.done():
                        agent.abort()
                        streaming_task.cancel()
                        try:
                            await streaming_task
                        except asyncio.CancelledError:
                            pass

                    text = msg.get("text", "")
                    # 将 streaming 作为后台 task 运行，不阻塞 WS 主循环
                    streaming_task = asyncio.create_task(
                        run_prompt_streaming(
                            websocket, agent, project, text, state
                        )
                    )

                elif msg_type == "abort":
                    agent.abort()

                elif msg_type == "switch_session":
                    sid = msg.get("session_id")
                    if sid:
                        agent.start_session(sid)
                        await websocket.send_json(
                            {
                                "type": "session_switched",
                                "session_id": sid,
                            }
                        )

        except WebSocketDisconnect:
            pass
        finally:
            if streaming_task is not None and not streaming_task.done():
                streaming_task.cancel()
                try:
                    await streaming_task
                except asyncio.CancelledError:
                    pass
            if play_task is not None and not play_task.done():
                play_session = state.get("play_session")
                if play_session is not None:
                    play_session.stop("connection closed")
                play_task.cancel()
                try:
                    await play_task
                except asyncio.CancelledError:
                    pass
            elif project.meta.get("status") == "playing":
                # 运行已自然结束但用户没点 Stop 就断开了连接——项目状态
                # 不该永远卡在 playing（下次打开这个项目会显示"运行中"）。
                await finalize_play(websocket, project)


    return app
