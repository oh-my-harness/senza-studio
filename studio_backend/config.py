"""Studio 全局配置。"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .auth import is_valid_api_token


DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:7878",
    "http://127.0.0.1:7878",
)


def _parse_allowed_origins(raw: str) -> tuple[str, ...]:
    origins: list[str] = []
    for candidate in (origin.strip() for origin in raw.split(",")):
        if not candidate:
            continue
        try:
            parsed = urlsplit(candidate)
            parsed.port
        except ValueError as error:
            raise ValueError("Invalid Senza Studio browser origin") from error
        if (
            parsed.scheme not in ("http", "https")
            or parsed.hostname is None
            or parsed.path not in ("", "/")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Invalid Senza Studio browser origin")
        origins.append(candidate)
    return tuple(dict.fromkeys(origins))


def _read_api_token_file(path_text: str) -> str:
    path = Path(path_text)
    try:
        file_descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError:
        raise ValueError("Senza Studio API token file is unavailable") from None

    try:
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Senza Studio API token file is invalid")
        if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError("Senza Studio API token file is not private")
        if metadata.st_size > 4096:
            raise ValueError("Senza Studio API token file is invalid")
        try:
            with os.fdopen(file_descriptor, "r", encoding="utf-8") as token_file:
                file_descriptor = -1
                token = token_file.read(4097).strip()
        except UnicodeError:
            raise ValueError("Senza Studio API token file is invalid") from None
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)

    if not is_valid_api_token(token):
        raise ValueError("Senza Studio API token is invalid")
    return token


@dataclass
class StudioConfig:
    """Studio 全局配置。"""
    home_dir: str = ""
    model: str = "deepseek-chat"
    api_key: str = ""
    api_base: str = ""
    agent_team_descriptor: str = ""
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS
    api_token: str = ""

    @classmethod
    def from_env(cls) -> StudioConfig:
        home = os.environ.get(
            "SENZA_STUDIO_HOME",
            str(Path.home() / ".senza-studio"),
        )
        allowed_origins = _parse_allowed_origins(
            os.environ.get("SENZA_STUDIO_ALLOWED_ORIGINS", "")
        )
        token = os.environ.get("SENZA_STUDIO_API_TOKEN", "")
        token_file = os.environ.get("SENZA_STUDIO_API_TOKEN_FILE", "")
        if token and token_file:
            raise ValueError("Configure only one Senza Studio API token source")
        if token_file:
            token = _read_api_token_file(token_file)
        elif token and not is_valid_api_token(token):
            raise ValueError("Senza Studio API token is invalid")
        return cls(
            home_dir=home,
            # 跟 api_key/api_base 一样支持 OPENAI_* 回落：SENZA_STUDIO_MODEL
            # 是"显式指定 Studio 用哪个模型"（设置面板里会因此置灰），
            # OPENAI_MODEL 只是通用兜底，不该锁死面板——不然任何 export 过
            # OPENAI_MODEL 的人都改不了模型了。
            model=os.environ.get(
                "SENZA_STUDIO_MODEL",
                os.environ.get("OPENAI_MODEL", "deepseek-chat"),
            ),
            api_key=os.environ.get(
                "SENZA_STUDIO_API_KEY", os.environ.get("OPENAI_API_KEY", "")
            ),
            api_base=os.environ.get(
                "SENZA_STUDIO_API_BASE",
                os.environ.get("OPENAI_API_BASE", ""),
            ),
            agent_team_descriptor=os.environ.get(
                "SENZA_STUDIO_AGENT_TEAM_DESCRIPTOR", ""
            ),
            allowed_origins=allowed_origins or DEFAULT_ALLOWED_ORIGINS,
            api_token=token,
        )

    @property
    def projects_dir(self) -> Path:
        return Path(self.home_dir) / "projects"
