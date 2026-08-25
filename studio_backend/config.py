"""Studio 全局配置。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StudioConfig:
    """Studio 全局配置。"""
    home_dir: str = ""
    model: str = "deepseek-chat"
    api_key: str = ""
    api_base: str = ""

    @classmethod
    def from_env(cls) -> StudioConfig:
        home = os.environ.get(
            "SENZA_STUDIO_HOME",
            str(Path.home() / ".senza-studio"),
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
        )

    @property
    def projects_dir(self) -> Path:
        return Path(self.home_dir) / "projects"
