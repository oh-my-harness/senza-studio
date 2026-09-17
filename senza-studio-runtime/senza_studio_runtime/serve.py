"""导出 Agent 的 HTTP/WS 服务。

这里提供的是**产品契约**，不是编辑器契约。导出的东西是"做好的 agent"本身，
不是做它用的工具——DAG、Inspector、Play/Pause/Step 这些属于 Studio，属于开发
和调试阶段，不属于交付物（Unity 导出的游戏里没有场景编辑器）。

所以这一层刻意不暴露 spec：

- ``GET /api/agent`` 只回**渲染界面需要的东西**——要用户填哪几个输入、每个
  step 该怎么展示（``ui.display``）、哪些 step 会停下来等人工决定。spec 的图
  结构（谁连谁、prompt 怎么写、用了哪些工具）一个字都不回。前端因此在结构上
  就画不出 DAG，而不是"画得出但我们不画"。
- ``WS /ws/run`` 只有三个动词：start / decision / cancel。没有 pause / resume
  / step——那是调试器的动词。

``ui.display`` 的分派规则和 Studio 的 Game view 完全一致（默认 chat，``none``
不展示）：spec 作者在 Studio 里看到的效果，就是最终用户看到的效果。
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .play import PlaySession, create_provider, get_entry_inputs
from .preprocess import PreprocessError, preprocess_spec
from .stream import run_play_streaming

# ui.display 没写时按 chat 渲染——和 Studio 的 Game view 同一个默认值
# （GameView.tsx 的 displayConfigFor）。两边默认值不一致的话，作者在 Studio
# 里看到的和用户在导出产品里看到的就不是一回事。
DEFAULT_DISPLAY = "chat"


def load_spec(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "stages" not in data:
        raise ValueError(f"{path} 不是合法的 pipeline（缺少 stages）")
    return data


def load_manifest(root: Path) -> dict:
    """agent.json——导出时写的展示信息（人类可读的名字等）。

    名字不放进 pipeline.yaml：那是流程定义，不该塞展示用的元数据。没有这个
    文件（比如手写的 pipeline）就退回目录名。
    """
    path = root / "agent.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def describe_steps(spec_dict: dict) -> dict[str, dict]:
    """展开后的 spec → 每个 step 的**展示契约**。

    只有三件事：怎么展示、展示哪些字段、停下来时有哪些选项。刻意不回
    prompt_template / tool / next_on_* 的目标——前端不需要知道流程长什么样。

    收编辑态 spec，内部先 preprocess：能力组件展开出来的 step（gate_review
    之类）在编辑态里根本不存在，而它恰恰常常就是那个要人工审批的 step。
    """
    steps: dict[str, dict] = {}
    for stage in preprocess_spec(spec_dict).get("stages", []):
        name = stage.get("name")
        if not name:
            continue
        ui = stage.get("ui") or {}
        steps[name] = {
            "display": ui.get("display") or DEFAULT_DISPLAY,
            "fields": ui.get("fields") or [],
            # 暂停等人工决定时给用户的选项。标签就是 next_on_* 的后缀，
            # 不写死"批准/拒绝"——spec 作者可以定义任意标签。
            #
            # 只给 checker：只有它会停下来问人。给别的 step 也算 choices 的话
            # 等于把"这一步之后能走哪几条分支"告诉了前端——那是流程结构，
            # 产品界面不需要知道（用户实测的 spec 里，classify_message 的三个
            # 分类分支就会这样漏出去）。
            "choices": sorted(
                key[len("next_on_"):]
                for key, value in stage.items()
                if key.startswith("next_on_") and isinstance(value, str)
            )
            if stage.get("type") == "checker"
            else [],
            # 终点 step。前端据此把最后一张卡片渲染成"结果"而不是"过程"。
            "terminal": stage.get("type") == "terminal",
        }
    return steps


def create_app(pipeline: Path, webui_dist: Path | None = None) -> FastAPI:
    """pipeline 是 pipeline.yaml 的路径；它所在的目录就是项目根目录
    （tools/ 和 plugins/ 在旁边）。"""
    pipeline = pipeline.resolve()
    root = pipeline.parent
    spec_dict = load_spec(pipeline)
    manifest = load_manifest(root)

    model = os.environ.get("SENZA_STUDIO_MODEL") or os.environ.get(
        "OPENAI_MODEL", "deepseek-chat"
    )
    api_key = os.environ.get("SENZA_STUDIO_API_KEY") or os.environ.get(
        "OPENAI_API_KEY", ""
    )
    api_base = os.environ.get("SENZA_STUDIO_API_BASE") or os.environ.get(
        "OPENAI_API_BASE", ""
    )

    app = FastAPI(title="Senza Agent", docs_url=None, redoc_url=None)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/agent")
    async def agent():
        """界面渲染所需的全部信息。一次请求拿齐，前端不用再拼第二个接口。

        展不开的组件不抛 500：产品界面该显示一条"这个 agent 装坏了"，而不是
        白屏。inputs/steps 给空，error 说明原因。
        """
        info: dict[str, Any] = {
            "name": manifest.get("name") or root.name,
            "description": manifest.get("description") or "",
            "inputs": [],
            "steps": {},
            "error": None,
        }
        try:
            info["inputs"] = get_entry_inputs(spec_dict)
            info["steps"] = describe_steps(spec_dict)
        except PreprocessError as exc:
            info["error"] = str(exc)
        return info

    @app.websocket("/ws/run")
    async def run_ws(websocket: WebSocket):
        await websocket.accept()
        play_session: PlaySession | None = None
        play_task: asyncio.Task | None = None
        try:
            while True:
                msg = await websocket.receive_json()
                msg_type = msg.get("type")

                if msg_type == "start":
                    if play_task is not None and not play_task.done():
                        continue  # 已经在跑，忽略重复 start
                    play_session = PlaySession(
                        root=root,
                        spec=spec_dict,
                        model=model,
                        provider=create_provider(api_key, api_base),
                    )
                    try:
                        play_session.play(inputs=msg.get("inputs"))
                    except Exception as exc:  # noqa: BLE001
                        # 构建阶段就失败（多半是组件展不开）。不接住的话异常会
                        # 穿出 handler 把连接打死，前端只看到一个莫名其妙断开的
                        # socket——Studio 那边踩过同样的坑。
                        play_session = None
                        await websocket.send_json(
                            {"type": "error", "message": f"无法启动: {exc}"}
                        )
                        continue
                    play_task = asyncio.create_task(
                        run_play_streaming(websocket, play_session)
                    )

                elif msg_type == "decision":
                    if play_session is not None:
                        step_id = msg.get("step_id")
                        decision = msg.get("decision")
                        if step_id and decision:
                            play_session.submit_decision(step_id, decision)

                elif msg_type == "cancel":
                    if play_session is not None:
                        play_session.stop("user cancel")
                    if play_task is not None and not play_task.done():
                        try:
                            await play_task
                        except asyncio.CancelledError:
                            pass
                    else:
                        try:
                            await websocket.send_json({"type": "play_stopped"})
                        except Exception:  # noqa: BLE001
                            pass

                # pause / resume / step 是调试器的动词，导出产品没有——发过来
                # 也静默忽略。
        except WebSocketDisconnect:
            if play_session is not None:
                play_session.stop("client disconnected")

    # 静态前端放在最后挂：它用 "/" 兜底，先挂会把上面的 API 路由盖掉。
    if webui_dist is not None and webui_dist.is_dir():
        index = webui_dist / "index.html"

        if (webui_dist / "assets").is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=webui_dist / "assets"),
                name="assets",
            )

        # index.html 必须每次回源校验。Vite 给 JS/CSS 的文件名带内容哈希
        # （index-BfmK6woV.js），所以资源本身可以放心长期缓存；但 index.html
        # 一旦被缓存住，它引用的就是**上一次构建**的哈希，那个文件在新的导出
        # 目录里根本不存在——浏览器于是一直请求一个 404 的 js，页面白屏，而且
        # 刷新也好不了（刷新用的还是缓存里的 html）。用户实测踩到过：
        # 反复 GET /assets/index-DJB5ylf1.js 404，而磁盘上是 index-BfmK6woV.js。
        #
        # 没有 Cache-Control 时浏览器会按启发式规则自己决定缓存多久（通常是
        # Last-Modified 距今时长的 10%），所以"不设"不等于"不缓存"。
        NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}

        @app.get("/{full_path:path}")
        async def spa(full_path: str):
            # SPA 兜底：非 /api、非 /ws 的路径一律回 index.html
            candidate = (webui_dist / full_path).resolve()
            if (
                full_path
                and candidate.is_file()
                and candidate.is_relative_to(webui_dist.resolve())
            ):
                return FileResponse(candidate)
            if index.is_file():
                return FileResponse(index, headers=NO_CACHE)
            return JSONResponse(status_code=404, content={"detail": "no webui"})

    return app


def serve(
    pipeline: Path, host: str = "127.0.0.1", port: int = 8000
) -> None:  # pragma: no cover - 薄封装
    import uvicorn

    dist = pipeline.resolve().parent / "webui" / "dist"
    uvicorn.run(
        create_app(pipeline, dist if dist.is_dir() else None), host=host, port=port
    )
