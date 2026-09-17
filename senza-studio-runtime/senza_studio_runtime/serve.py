"""导出项目的 HTTP/WS 服务（Phase 7 切片三）。

只提供 **Play 那一部分**契约：加载 spec、问入口输入、展开组件、跑流程。
没有对话，也不能改 spec——导出的是一个跑流程的项目，不是编辑器。

路由沿用 Studio 的形状（``/api/projects/{id}/...``），project id 固定成
``default``。这样导出包里那份 Studio 前端构建产物一个字都不用改就能用；
真去另发明一套 URL，前端就得跟着分叉。
"""
from __future__ import annotations

import asyncio
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

# 导出项目只有一个流程。沿用 Studio 的路由形状，但 id 固定。
PROJECT_ID = "default"


def load_spec(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "stages" not in data:
        raise ValueError(f"{path} 不是合法的 pipeline（缺少 stages）")
    return data


def create_app(pipeline: Path, webui_dist: Path | None = None) -> FastAPI:
    """pipeline 是 pipeline.yaml 的路径；它所在的目录就是项目根目录
    （tools/ 和 plugins/ 在旁边）。"""
    pipeline = pipeline.resolve()
    root = pipeline.parent
    spec_dict = load_spec(pipeline)

    model = os.environ.get("SENZA_STUDIO_MODEL") or os.environ.get(
        "OPENAI_MODEL", "deepseek-chat"
    )
    api_key = os.environ.get("SENZA_STUDIO_API_KEY") or os.environ.get(
        "OPENAI_API_KEY", ""
    )
    api_base = os.environ.get("SENZA_STUDIO_API_BASE") or os.environ.get(
        "OPENAI_API_BASE", ""
    )

    app = FastAPI(title="Senza Studio Runtime", docs_url=None, redoc_url=None)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/mode")
    async def mode():
        """前端据此进入 export 模式：不渲染对话面板、spec 只读。"""
        return {"mode": "export", "project_id": PROJECT_ID}

    @app.get("/api/projects")
    async def list_projects():
        # 前端的项目列表页复用同一个接口；导出项目永远只有这一个。
        return [{"id": PROJECT_ID, "name": root.name, "status": "editing"}]

    @app.get("/api/projects/{project_id}")
    async def get_project(project_id: str):
        return {"id": PROJECT_ID, "name": root.name, "status": "editing"}

    @app.get("/api/projects/{project_id}/spec")
    async def get_spec(project_id: str):
        return spec_dict

    @app.get("/api/projects/{project_id}/entry_inputs")
    async def entry_inputs(project_id: str):
        return {"fields": get_entry_inputs(spec_dict)}

    @app.get("/api/projects/{project_id}/expanded_spec")
    async def expanded_spec(project_id: str):
        try:
            return {"spec": preprocess_spec(spec_dict), "error": None}
        except PreprocessError as exc:
            return {"spec": None, "error": str(exc)}

    @app.get("/api/projects/{project_id}/messages")
    async def messages(project_id: str):
        # 没有对话历史，但前端启动时会读一次——返回空列表比 404 干净。
        return []

    @app.websocket("/ws/projects/{project_id}")
    async def project_ws(websocket: WebSocket, project_id: str):
        await websocket.accept()
        play_session: PlaySession | None = None
        play_task: asyncio.Task | None = None
        try:
            while True:
                msg = await websocket.receive_json()
                msg_type = msg.get("type")

                if msg_type == "play":
                    if play_task is not None and not play_task.done():
                        continue  # 已经在跑，忽略重复 play
                    play_session = PlaySession(
                        root=root,
                        spec=spec_dict,
                        model=model,
                        provider=create_provider(api_key, api_base),
                    )
                    try:
                        play_session.play(
                            inputs=msg.get("inputs"),
                            start_paused=bool(msg.get("start_paused")),
                        )
                    except Exception as exc:  # noqa: BLE001
                        # 构建阶段就失败（多半是组件展不开）。不接住的话异常会
                        # 穿出 handler 把连接打死，前端只看到一个莫名其妙断开的
                        # socket——Studio 那边踩过同样的坑。
                        play_session = None
                        await websocket.send_json(
                            {"type": "error", "message": f"无法启动 Play: {exc}"}
                        )
                        continue
                    play_task = asyncio.create_task(
                        run_play_streaming(websocket, play_session)
                    )

                elif msg_type == "stop":
                    if play_session is not None:
                        play_session.stop("user stop")
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

                elif msg_type == "submit_decision":
                    if play_session is not None:
                        step_id = msg.get("step_id")
                        decision = msg.get("decision")
                        if step_id and decision:
                            play_session.submit_decision(step_id, decision)

                elif msg_type == "pause":
                    if play_session is not None:
                        play_session.request_pause()

                elif msg_type == "resume":
                    if play_session is not None:
                        play_session.resume_run()

                elif msg_type == "step":
                    if play_session is not None:
                        play_session.step()

                # 其余消息（prompt 等）导出项目不支持，静默忽略：前端在
                # export 模式下不会发，发了也只是没有对话功能而已。
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
