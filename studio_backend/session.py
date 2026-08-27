"""元 agent session 生命周期管理。

Session 是元 agent 的对话历史持久化。每个 session 是一个目录，
包含 meta.json（元信息）和 entries.jsonl（对话条目）。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
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


def _to_epoch_ms(iso_ts: str | None) -> int:
    if not iso_ts:
        return int(time.time() * 1000)
    ts = iso_ts.replace("Z", "+00:00")
    return int(datetime.fromisoformat(ts).timestamp() * 1000)


def read_session_history(sessions_dir: Path, session_id: str) -> list[dict]:
    """把 entries.jsonl 里的持久化条目还原成前端 ChatMessage[] 形状。

    与 ChatPanel 实时拼装消息的规则保持一致：只展示 text 内容，跳过
    thinking；每个 tool_use 拆成单独的 "tool" 角色气泡（对应实时流里的
    tool_call_start），tool_result 同理（对应实时流里的 tool_result）。
    """
    path = session_file_path(sessions_dir, session_id)
    if not path.exists():
        return []

    messages: list[dict] = []
    tool_names: dict[str, str] = {}  # tool_use_id -> tool name

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        entry = json.loads(line)
        payload = entry.get("payload", {})
        role = payload.get("role")
        ts = _to_epoch_ms(payload.get("timestamp"))
        parts = payload.get("content") or []

        if role == "user":
            text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
            if text:
                messages.append({"role": "user", "content": text, "timestamp": ts})

        elif role == "assistant":
            text_buf = ""
            for p in parts:
                ptype = p.get("type")
                if ptype == "text":
                    text_buf += p.get("text", "")
                elif ptype == "tool_use":
                    if text_buf:
                        messages.append({"role": "assistant", "content": text_buf, "timestamp": ts})
                        text_buf = ""
                    name = p.get("name", "")
                    tool_names[p.get("id", "")] = name
                    messages.append(
                        {"role": "tool", "content": f"调用工具: {name}", "toolName": name, "timestamp": ts}
                    )
                # thinking 部分不展示，与实时流一致
            if text_buf:
                messages.append({"role": "assistant", "content": text_buf, "timestamp": ts})

        elif role == "tool_result":
            text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
            name = tool_names.get(payload.get("tool_use_id", ""), "")
            messages.append(
                {"role": "tool", "content": f"结果: {text}", "toolName": name, "timestamp": ts}
            )

    return messages
