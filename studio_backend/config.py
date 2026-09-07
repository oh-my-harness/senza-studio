"""Studio 全局配置。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


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


@dataclass
class StudioConfig:
    """Studio 全局配置。"""
    home_dir: str = ""
    model: str = "deepseek-chat"
    api_key: str = ""
    api_base: str = ""
    agent_team_descriptor: str = ""
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS

    @classmethod
    def from_env(cls) -> StudioConfig:
        home = os.environ.get(
            "SENZA_STUDIO_HOME",
            str(Path.home() / ".senza-studio"),
        )
        allowed_origins = _parse_allowed_origins(
            os.environ.get("SENZA_STUDIO_ALLOWED_ORIGINS", "")
        )
        return cls(
            home_dir=home,
            model=os.environ.get("SENZA_STUDIO_MODEL", "deepseek-chat"),
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
        )

    @property
    def projects_dir(self) -> Path:
        return Path(self.home_dir) / "projects"
