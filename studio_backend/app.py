"""FastAPI application factory + REST endpoints + WebSocket."""
from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import StudioConfig
from .project import Project
from .spec import Spec, SpecError
from .agent import StudioAgent
from .ws import run_prompt_streaming


class CreateProjectReq(BaseModel):
    name: str


class UpdateSpecReq(BaseModel):
    spec: dict


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
    app = FastAPI(title="Senza Studio")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    cfg = config or StudioConfig.from_env()

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

    # ── Spec ─────────────────────────────────────────────
    @app.get("/api/projects/{project_id}/spec")
    async def get_spec(project_id: str):
        state = _get_or_load_project(cfg, project_id)
        return state["spec"].get_current_spec()

    @app.put("/api/projects/{project_id}/spec")
    async def update_spec(project_id: str, req: UpdateSpecReq):
        state = _get_or_load_project(cfg, project_id)
        # 替换 spec 内容
        new_spec = Spec(req.spec)
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

    # ── WebSocket ────────────────────────────────────────
    @app.websocket("/ws/projects/{project_id}")
    async def project_ws(websocket: WebSocket, project_id: str):
        await websocket.accept()
        state = _get_or_load_project(cfg, project_id)
        agent = state["agent"]
        project = state["project"]
        spec = state["spec"]

        # 如果 agent 还没启动 session，启动一个
        if agent._harness is None:
            active = project.meta.get("active_session")
            agent.start_session(active)

        try:
            while True:
                msg = await websocket.receive_json()
                msg_type = msg.get("type")

                if msg_type == "prompt":
                    text = msg.get("text", "")
                    await run_prompt_streaming(
                        websocket, agent, project, spec, text
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

    return app
