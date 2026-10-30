"""元 agent session 生命周期管理。

Session 是元 agent 的对话历史持久化。每个 session 是一个目录，
包含 meta.json（元信息）和 entries.jsonl（对话条目）。
"""
from __future__ import annotations

import json
import sys
import time
import uuid
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


def _valid_uuid(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"session entry {label} is not a UUID: {value!r}")
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise RuntimeError(f"session entry {label} is not a UUID: {value!r}") from exc
    return value


def _uuid_key(value: str) -> str:
    # runtime 的 Uuid 解析大小写不敏感；比较/去重必须按规范形式。
    return str(uuid.UUID(value))


def _validate_entry(entry: object, line_no: int) -> tuple[str, str | None]:
    """校验 runtime SessionEntry 的最低持久化结构。

    这里不复制 runtime 的完整 serde 实现，只拒绝会导致 jsonl_session_repo
    无法反序列化或沿 parent 链走到不存在节点的形状。未知 entry_type 仍允许：
    runtime 用 #[serde(other)] 保留新版本写入的条目。
    """
    if not isinstance(entry, dict):
        raise RuntimeError(f"session entry line {line_no} is not an object")
    if "parent_id" not in entry:
        raise RuntimeError(f"session entry line {line_no} is missing parent_id")
    entry_id = _valid_uuid(entry.get("id"), f"line {line_no} id")
    parent_id = entry.get("parent_id")
    if parent_id is not None:
        parent_id = _valid_uuid(parent_id, f"line {line_no} parent_id")
    timestamp = entry.get("timestamp")
    if not isinstance(timestamp, str) or _parse_timestamp(timestamp) is None:
        raise RuntimeError(
            f"session entry line {line_no} has an invalid timestamp: {timestamp!r}"
        )
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError(f"session entry line {line_no} has no payload object")
    entry_type = payload.get("entry_type")
    if not isinstance(entry_type, str) or not entry_type:
        raise RuntimeError(
            f"session entry line {line_no} has no payload.entry_type"
        )
    policy = entry.get("compaction_policy")
    if policy not in (None, "compact", "keep"):
        raise RuntimeError(
            f"session entry line {line_no} has invalid compaction_policy: {policy!r}"
        )
    return entry_id, parent_id


def _read_session_entries(entries_path: Path) -> list[dict]:
    """读取并校验 entries.jsonl；只容忍最后一行没有换行的半写记录。

    旧实现从后往前找“任意一条能解析的 id”，中间损坏/截断会被静默跳过，
    重建 meta 时可能把游标接回一条无法沿链回根的条目。这里逐行校验：
    - 中间行损坏 → 明确报错，不猜、不改原文件；
    - 最后一行无换行且 JSON 不完整 → 视为进程中断的半写行，忽略它，
      但保留原始字节；
    - 条目 UUID/parent/timestamp/payload/compaction_policy 形状错误 → 报错。
    """
    try:
        raw = entries_path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"session entries unreadable: {entries_path}: {exc}") from exc

    entries: list[dict] = []
    seen: set[str] = set()
    # 必须按字节 '\n' 切行，不能用 str.splitlines()：后者还会在 U+2028/
    # U+2029/U+0085 处断行，而这些是 JSON 字符串里合法的字符。
    raw_lines = raw.split(b"\n")
    file_ends_with_newline = raw.endswith((b"\n", b"\r"))
    for index, raw_line in enumerate(raw_lines):
        raw_line = raw_line.rstrip(b"\r")
        if not raw_line.strip():
            continue
        is_last_line = index == len(raw_lines) - 1
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError as exc:
            if is_last_line and not file_ends_with_newline:
                # 半写尾行可能截断多字节字符；保留原始字节，只恢复已完整
                # 校验的前缀。中间行非法 UTF-8 仍然必须显式报错。
                break
            raise RuntimeError(
                f"session entry line {index + 1} is not valid UTF-8: {exc}"
            ) from exc
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError) as exc:
            if is_last_line and not file_ends_with_newline:
                # 半写尾部不是“可安全恢复的完整条目”；保留字节，返回已
                # 校验过的前缀。若 meta 游标指向它，后续 reachability 会报错。
                break
            raise RuntimeError(
                f"session entry line {index + 1} is corrupt: {exc}"
            ) from exc
        entry_id, _parent_id = _validate_entry(entry, index + 1)
        entry_key = _uuid_key(entry_id)
        if entry_key in seen:
            raise RuntimeError(f"duplicate session entry id at line {index + 1}: {entry_id}")
        seen.add(entry_key)
        entries.append(entry)
    return entries


def _assert_cursor_reachable(entries: list[dict], cursor: str | None) -> None:
    if cursor is None:
        return
    _valid_uuid(cursor, "active_cursor")
    by_id = {_uuid_key(entry["id"]): entry for entry in entries}
    seen: set[str] = set()
    current: str | None = _uuid_key(cursor)
    while current is not None:
        if current in seen:
            raise RuntimeError(f"session active_cursor contains a parent cycle at {current}")
        seen.add(current)
        entry = by_id.get(current)
        if entry is None:
            raise RuntimeError(
                f"session active_cursor {cursor} is not reachable: missing entry {current}"
            )
        parent = entry.get("parent_id")
        current = _uuid_key(parent) if parent is not None else None


def _last_entry_id(entries: list[dict]) -> str | None:
    """返回校验过的最后一条 entry 的 id（用于缺失/损坏 meta 的修复）。"""
    return entries[-1]["id"] if entries else None


def ensure_session(sessions_dir: Path, session_id: str) -> Path:
    """确保 session 目录结构存在且 meta 可被 runtime 打开。

    目录存在但 meta 缺失/截断/schema 错是进程中断的常见残留。缺失的 meta
    可以安全重建；损坏/不合法 meta 必须先隔离原始字节再重建，绝不覆盖。
    entries.jsonl 只做 missing-touch，绝不在 prompt 可能追加时重写。
    """
    sdir = session_dir_path(sessions_dir, session_id)
    sdir.mkdir(parents=True, exist_ok=True)
    meta_path = sdir / "meta.json"
    entries_path = sdir / "entries.jsonl"

    if entries_path.exists() and not entries_path.is_file():
        raise RuntimeError(f"session entries path is not a file: {entries_path}")

    # 先校验 entries，再决定是否写 meta。否则坏 entries 可能配上新 meta，
    # 让下一次打开误以为已经修复。缺失 entries 等价于空 session。
    entries = _read_session_entries(entries_path) if entries_path.exists() else []

    meta: dict | None = None
    valid = False
    if meta_path.exists():
        try:
            raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            valid = _session_meta_is_valid(raw_meta, session_id)
            if valid:
                meta = raw_meta
            reason = "invalid session meta"
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            reason = f"unreadable session meta: {exc}"
        if not valid:
            if quarantine_file(meta_path, reason=reason) is None and meta_path.exists():
                raise RuntimeError(
                    f"session meta is invalid and could not be quarantined: {meta_path}"
                )

    if meta is not None:
        # 合法 meta 是权威状态。只有 cursor 指向不存在/断链/成环的条目时
        # 才拒绝加载：不能猜一个“差不多”的 cursor 覆盖 runtime 的语义。
        _assert_cursor_reachable(entries, meta.get("active_cursor"))
    else:
        repaired = _minimal_session_meta(session_id)
        # 修复损坏/缺失 meta 时保留历史链：runtime 的 build_context 只从
        # active_cursor 走；置 None 会把已有 entries 变成不可达的孤立分支。
        repaired["active_cursor"] = _last_entry_id(entries)
        _assert_cursor_reachable(entries, repaired["active_cursor"])
        atomic_write_text(
            meta_path,
            json.dumps(repaired, ensure_ascii=False),
        )

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

    # 已经由 _read_session_entries 校验过；这里按解析后的 entry 处理，
    # 不再用 str.splitlines() 重切 JSON（U+2028/U+2029 是合法字符串内容）。
    entries = _read_session_entries(path)

    for entry in entries:
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
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

    return messages
