"""senza-sdk 版本 pin 校验。

Studio 对 senza-sdk 的所有假设（system prompt 里描述的能力、agent.py/
tools/*.py 里调用的具体函数）只在 senza-sdk.lock 记录的版本下被验证过。
这个模块在启动时做一次校验，把"装的 SDK 和上次验证的不一致"从静默隐患
变成可见的警告（或 strict 模式下的硬错误）。

不检查时的真实风险：本 session 里就发生过——一个过期的预构建 wheel
（senza_sdk-0.3.0）曾让 agent.py 里的每一个 senza 调用看起来都不存在，
直到有人手动发现。这个模块是防止同类问题再次静默发生的最小闭环之一半
（另一半是 scripts/check_senza_compat.py 的 API 级校验）。
"""
from __future__ import annotations

import importlib.metadata
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
LOCK_PATH = _REPO_ROOT / "senza-sdk.lock"


class SdkPinMismatch(RuntimeError):
    """Raised in strict mode when the installed senza-sdk doesn't match the recorded pin."""


def check_sdk_pin(strict: bool | None = None) -> None:
    """Compare the installed senza-sdk version against senza-sdk.lock.

    Logs a warning on mismatch or missing lock file. If `strict` (or the
    SENZA_STUDIO_STRICT_SDK_PIN env var) is true, raises SdkPinMismatch
    instead — intended for CI, not local dev, so a routine version bump
    doesn't brick everyone's local iteration.
    """
    if strict is None:
        strict = os.environ.get("SENZA_STUDIO_STRICT_SDK_PIN", "") not in ("", "0", "false")

    if not LOCK_PATH.exists():
        _warn_or_raise(
            strict,
            f"No senza-sdk.lock found at {LOCK_PATH} — Studio's SDK compatibility has "
            "never been recorded. Run ./dev.sh to build/install senza-sdk and record a pin.",
        )
        return

    try:
        locked = json.loads(LOCK_PATH.read_text())
        locked_version = locked["senza_version"]
    except (json.JSONDecodeError, KeyError, OSError) as e:
        _warn_or_raise(strict, f"senza-sdk.lock is unreadable/malformed ({e}) — treating as unpinned.")
        return

    try:
        installed_version = importlib.metadata.version("senza-sdk")
    except importlib.metadata.PackageNotFoundError:
        _warn_or_raise(
            strict,
            "senza-sdk is not installed in this environment, but senza-sdk.lock expects "
            f"version {locked_version}. Run ./dev.sh.",
        )
        return

    if installed_version != locked_version:
        _warn_or_raise(
            strict,
            f"senza-sdk version mismatch: locked={locked_version}, installed={installed_version} — "
            "Studio has not been re-verified against this version. Run "
            "scripts/check_senza_compat.py to check for API drift, then update senza-sdk.lock.",
        )
        return

    logger.info("senza-sdk pin OK (version=%s)", installed_version)


def _warn_or_raise(strict: bool, message: str) -> None:
    if strict:
        raise SdkPinMismatch(message)
    logger.warning(message)
