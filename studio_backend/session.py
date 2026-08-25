"""元 agent session 生命周期管理。

Session 是元 agent 的对话历史持久化。每个 session 是一个目录，
包含 meta.json（元信息）和 entries.jsonl（对话条目）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def session_dir_path(sessions_dir: Path, session_id: str) -> Path:
    """返回 session 目录路径。"""
    return sessions_dir / session_id


def session_file_path(sessions_dir: Path, session_id: str) -> Path:
    """返回 session entries.jsonl 文件路径。"""
    return session_dir_path(sessions_dir, session_id) / "entries.jsonl"


def session_exists(sessions_dir: Path, session_id: str) -> bool:
    """检查 session 是否存在（目录 + meta.json）。"""
    return (session_dir_path(sessions_dir, session_id) / "meta.json").exists()


def ensure_session(sessions_dir: Path, session_id: str) -> Path:
    """确保 session 目录结构存在。如果不存在则创建。

    返回 session 目录路径。senza 的 jsonl_session_repo 要求每个 session
    是一个目录，包含 meta.json 和 entries.jsonl。
    """
    sdir = session_dir_path(sessions_dir, session_id)
    if not sdir.exists():
        sdir.mkdir(parents=True, exist_ok=True)
        now = _utc_now()
        meta = {
            "id": session_id,
            "created_at": now,
            "updated_at": now,
            "model": None,
            "name": None,
            "active_cursor": None,
            "parent_session_path": None,
        }
        (sdir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        (sdir / "entries.jsonl").touch()
    return sdir
