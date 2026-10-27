"""小文件的安全写入原语。

Studio 的 pipeline.yaml / meta.json / session meta 都是“整文件替换”语义：
写入过程中崩溃、磁盘满或权限错误不能留下 0 字节或截断文件。这里统一用
同目录临时文件 + fsync + os.replace，保证读者看到的要么是旧内容，要么是
完整的新内容。
"""
from __future__ import annotations

import os
import stat
import sys
import tempfile
import time
from pathlib import Path


def _fsync_directory(directory: Path) -> None:
    """POSIX 上把 rename 也刷到目录项；Windows 不支持，忽略。"""
    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _replace_with_retry(src: Path, dst: Path, attempts: int = 3) -> None:
    """Windows/DrvFs 上 replace 可能被短暂占用；有限重试后仍然失败就抛出。"""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(0.05 * (attempt + 1))


def atomic_write_text(
    path: Path,
    text: str,
    *,
    mode: int | None = None,
) -> None:
    """原子替换文本文件。

    mode 为 None 时保留目标文件已有权限；新文件默认 0o600（Studio 数据
    目录里不需要其他用户读）。调用方负责决定更宽松的权限。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    target_mode = mode
    if target_mode is None:
        try:
            target_mode = stat.S_IMODE(path.stat().st_mode)
        except OSError:
            target_mode = 0o600

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), target_mode)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if not hasattr(os, "fchmod"):
            os.chmod(tmp, target_mode)
        _replace_with_retry(tmp, path)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    mode: int | None = None,
) -> None:
    """原子替换二进制文件（上传原文等）。语义与 atomic_write_text 一致。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    target_mode = mode
    if target_mode is None:
        try:
            target_mode = stat.S_IMODE(path.stat().st_mode)
        except OSError:
            target_mode = 0o600
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), target_mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if not hasattr(os, "fchmod"):
            os.chmod(tmp, target_mode)
        _replace_with_retry(tmp, path)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def quarantine_file(path: Path, *, reason: str) -> Path | None:
    """把损坏文件改名保留原始字节，绝不静默覆盖。

    返回隔离后的路径；文件不存在或改名失败时返回 None（失败会打印原因，
    调用方必须决定是否继续——通常应当继续抛出，而不是覆盖）。
    """
    path = Path(path)
    if not path.exists():
        return None
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = path.with_name(f"{path.name}.corrupt-{stamp}")
    suffix = 1
    while target.exists():
        target = path.with_name(f"{path.name}.corrupt-{stamp}-{suffix}")
        suffix += 1
    try:
        os.replace(path, target)
    except OSError as exc:
        print(f"could not quarantine {path}: {exc} ({reason})", file=sys.stderr)
        return None
    print(f"quarantined {path} -> {target} ({reason})", file=sys.stderr)
    return target
