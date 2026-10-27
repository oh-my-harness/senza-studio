"""元 agent session 生命周期管理。

Session 是元 agent 的对话历史持久化。每个 session 是一个目录，
包含 meta.json（元信息）和 entries.jsonl（对话条目）。
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .storage import atomic_write_text, quarantine_file


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Runtime 的 DateTime<Utc> 需要带时区；裸时间戳会在 repo.open 里失败。
    return parsed if parsed.tzinfo is not None else None


def _safe_session_dir(sessions_dir: Path, session_id: str) -> Path:
    if (
        not isinstance(session_id, str)
        or not session_id
        or session_id in (".", "..")
        or "/" in session_id
        or "\\" in session_id
        or Path(session_id).is_absolute()
    ):
        raise ValueError(f"invalid session id: {session_id!r}")
    root = sessions_dir.resolve()
    sdir = (sessions_dir / session_id).resolve()
    if sdir == root or not sdir.is_relative_to(root):
        raise ValueError(f"session id escapes sessions dir: {session_id!r}")
    return sdir


def session_dir_path(sessions_dir: Path, session_id: str) -> Path:
    """返回 session 目录路径（拒绝 .. / 绝对路径 / 路径分隔符）。"""
    return _safe_session_dir(sessions_dir, session_id)


def session_file_path(sessions_dir: Path, session_id: str) -> Path:
    """返回 session entries.jsonl 文件路径。"""
    return session_dir_path(sessions_dir, session_id) / "entries.jsonl"


def session_exists(sessions_dir: Path, session_id: str) -> bool:
    """检查 session 是否存在（目录 + meta.json）。"""
    return (session_dir_path(sessions_dir, session_id) / "meta.json").exists()


def _session_meta_is_valid(meta: object, session_id: str) -> bool:
    if not isinstance(meta, dict):
        return False
    if meta.get("id") != session_id:
        return False
    if not isinstance(meta.get("created_at"), str) or _parse_timestamp(meta["created_at"]) is None:
        return False
    if not isinstance(meta.get("updated_at"), str) or _parse_timestamp(meta["updated_at"]) is None:
        return False
    for key in ("model", "name"):
        value = meta.get(key)
        if value is not None and not isinstance(value, str):
            return False
    for key in ("active_cursor", "parent_session_path"):
        value = meta.get(key)
        if value is not None and not isinstance(value, str):
            return False
    return True


def _minimal_session_meta(session_id: str) -> dict:
    now = _utc_now()
    return {
        "id": session_id,
        "created_at": now,
        "updated_at": now,
        "model": None,
        "name": None,
        "active_cursor": None,
        "parent_session_path": None,
    }


def ensure_session(sessions_dir: Path, session_id: str) -> Path:
    """确保 session 目录结构存在且 meta 可被 runtime 打开。

    目录存在但 meta 缺失/截断/schema 错是进程中断的常见残留。缺失的 meta
    可以安全重建；损坏/不合法 meta 必须先隔离原始字节再重建，绝不覆盖。
    entries.jsonl 只做 missing-touch，绝不在 prompt 可能追加时重写。
    """
    sdir = session_dir_path(sessions_dir, session_id)
    sdir.mkdir(parents=True, exist_ok=True)
    meta_path = sdir / "meta.json"

    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            valid = _session_meta_is_valid(meta, session_id)
            reason = "invalid session meta"
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            valid = False
            reason = f"unreadable session meta: {exc}"
        if not valid:
            if quarantine_file(meta_path, reason=reason) is None and meta_path.exists():
                raise RuntimeError(
                    f"session meta is invalid and could not be quarantined: {meta_path}"
                )

    if not meta_path.exists():
        atomic_write_text(
            meta_path,
            json.dumps(_minimal_session_meta(session_id), ensure_ascii=False),
        )

    entries_path = sdir / "entries.jsonl"
    if entries_path.exists() and not entries_path.is_file():
        raise RuntimeError(f"session entries path is not a file: {entries_path}")
    if not entries_path.exists():
        entries_path.touch()
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

    # 只恢复 Studio 展示：runtime 对非法 UTF-8/无换行尾行仍按自己的策略处理。
    # 本项目历史是用户数据，不能因为最后一行写了一半就让整个项目打不开。
    try:
        content_text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"could not read session history {path}: {exc}", file=sys.stderr)
        return []

    for lineno, raw_line in enumerate(content_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if not isinstance(entry, dict):
                raise ValueError("entry is not an object")
            payload = entry.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload is not an object")
            role = payload.get("role")
            try:
                ts = _to_epoch_ms(payload.get("timestamp"))
            except (TypeError, ValueError):
                ts = int(time.time() * 1000)
            parts = payload.get("content")
            if not isinstance(parts, list):
                parts = []

            def text_of(part: object) -> str:
                if not isinstance(part, dict):
                    return ""
                value = part.get("text")
                return value if isinstance(value, str) else ""

            if role == "user":
                message_text = "".join(
                    text_of(p)
                    for p in parts
                    if isinstance(p, dict) and p.get("type") == "text"
                )
                if message_text:
                    messages.append(
                        {"role": "user", "content": message_text, "timestamp": ts}
                    )

            elif role == "assistant":
                text_buf = ""
                for p in parts:
                    if not isinstance(p, dict):
                        continue
                    ptype = p.get("type")
                    if ptype == "text":
                        text_buf += text_of(p)
                    elif ptype == "tool_use":
                        if text_buf:
                            messages.append(
                                {"role": "assistant", "content": text_buf, "timestamp": ts}
                            )
                            text_buf = ""
                        name = p.get("name") if isinstance(p.get("name"), str) else ""
                        tool_id = p.get("id") if isinstance(p.get("id"), str) else ""
                        tool_names[tool_id] = name
                        messages.append(
                            {
                                "role": "tool",
                                "content": f"调用工具: {name}",
                                "toolName": name,
                                "timestamp": ts,
                            }
                        )
                    # thinking 部分不展示，与实时流一致
                if text_buf:
                    messages.append(
                        {"role": "assistant", "content": text_buf, "timestamp": ts}
                    )

            elif role == "tool_result":
                message_text = "".join(
                    text_of(p)
                    for p in parts
                    if isinstance(p, dict) and p.get("type") == "text"
                )
                tool_use_id = payload.get("tool_use_id")
                name = tool_names.get(tool_use_id, "") if isinstance(tool_use_id, str) else ""
                messages.append(
                    {
                        "role": "tool",
                        "content": f"结果: {message_text}",
                        "toolName": name,
                        "timestamp": ts,
                    }
                )
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
            print(
                f"skipping malformed session entry {path}:{lineno}: {exc}",
                file=sys.stderr,
            )
            continue

    return messages
