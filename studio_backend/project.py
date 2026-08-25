"""项目管理：创建/打开/列出项目，meta.json 维护。"""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

from .config import StudioConfig
from .spec import Spec


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _gen_id(prefix: str = "proj") -> str:
    # 时间戳(毫秒) + 6 位随机后缀，避免同一毫秒内创建多个项目时 ID 碰撞
    return f"{prefix}-{int(time.time() * 1000)}-{secrets.token_hex(3)}"


class Project:
    """单个 Studio 项目。"""

    def __init__(self, config: StudioConfig, meta: dict, path: Path) -> None:
        self.config = config
        self.meta = meta
        self.path = path

    # ── 创建/打开/列出 ────────────────────────────────────

    @classmethod
    def create(cls, config: StudioConfig, name: str) -> Project:
        proj_id = _gen_id("proj")
        path = config.projects_dir / proj_id
        path.mkdir(parents=True, exist_ok=True)

        # 创建目录结构 (design-v2 §3)
        (path / ".studio" / "docs").mkdir(parents=True, exist_ok=True)
        (path / ".studio" / "specs").mkdir(parents=True, exist_ok=True)
        (path / ".studio" / "sessions").mkdir(parents=True, exist_ok=True)
        (path / "tools" / "generated").mkdir(parents=True, exist_ok=True)
        (path / "tools" / "custom").mkdir(parents=True, exist_ok=True)
        (path / "plugins").mkdir(parents=True, exist_ok=True)
        (path / "exports").mkdir(parents=True, exist_ok=True)

        meta = {
            "id": proj_id,
            "name": name,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "status": "editing",
            "model": config.model,
            "active_session": None,
            "sessions": [],
            "last_played_at": None,
            "last_export_dir": None,
        }

        # 初始空 spec
        spec = Spec()
        (path / "pipeline.yaml").write_text(spec.to_yaml(), encoding="utf-8")

        proj = cls(config, meta, path)
        proj._save_meta()
        return proj

    @classmethod
    def open(cls, config: StudioConfig, project_id: str) -> Project:
        path = config.projects_dir / project_id
        meta_path = path / ".studio" / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"project {project_id} not found")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return cls(config, meta, path)

    @classmethod
    def list_all(cls, config: StudioConfig) -> list[dict]:
        projects_dir = config.projects_dir
        if not projects_dir.exists():
            return []
        result = []
        for p in sorted(projects_dir.iterdir()):
            meta_path = p / ".studio" / "meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                result.append(meta)
        return result

    # ── Spec 持久化 ───────────────────────────────────────

    def save_spec(self, spec: Spec) -> None:
        yaml_path = self.path / "pipeline.yaml"
        yaml_path.write_text(spec.to_yaml(), encoding="utf-8")
        self.meta["updated_at"] = _utc_now()
        self._save_meta()

    def load_spec(self) -> Spec:
        yaml_path = self.path / "pipeline.yaml"
        if not yaml_path.exists():
            return Spec()
        return Spec.from_yaml(yaml_path.read_text(encoding="utf-8"))

    # ── Session 管理 ──────────────────────────────────────

    def create_session(self) -> str:
        sid = _gen_id("sess")
        self.meta.setdefault("sessions", []).append(sid)
        self.meta["active_session"] = sid
        self._save_meta()
        return sid

    def set_active_session(self, session_id: str) -> None:
        if session_id not in self.meta.get("sessions", []):
            raise ValueError(f"session {session_id} not found")
        self.meta["active_session"] = session_id
        self._save_meta()

    @property
    def sessions_dir(self) -> Path:
        return self.path / ".studio" / "sessions"

    # ── 内部 ──────────────────────────────────────────────

    def _save_meta(self) -> None:
        meta_path = self.path / ".studio" / "meta.json"
        meta_path.write_text(
            json.dumps(self.meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
