"""元 agent Harness 组装。

参考 senza-agent create_agent() 模式，简化：
- 去掉 advisor / acceptance gate / behavior bundle（Studio 元 agent 不需要）
- 去掉 web tools / code exec（元 agent 只做 spec 构建）
- 保留 safety / loop_safety / tool_output_guard / injection_filter
- 加 session_repo 实现持久化
- system prompt 动态组装
"""
from __future__ import annotations

import sys
from typing import Any

from .config import StudioConfig
from .project import Project
from .session import ensure_session
from .spec import Spec
from .system_prompt import build_system_prompt
from .tools.spec_tools import make_spec_tools
from .tools.doc_tools import make_doc_tools
from .tools.prefab_tools import make_prefab_tools


def _create_provider(config: StudioConfig) -> Any:
    """创建 LLM provider。参考 senza-agent config.create_provider。"""
    import senza

    api_key = config.api_key
    api_base = config.api_base if config.api_base else None
    return senza.providers.openai(api_key=api_key, base_url=api_base)


class StudioAgent:
    """管理一个元 agent Harness 实例。

    生命周期：
    1. __init__ — 存储引用，不 build
    2. start_session(session_id?) — build harness，绑定 session
    3. prompt(text) — 发送 prompt，返回事件列表
    4. rebuild() — spec/prompt 变化后重建 harness（保留 session）
    """

    def __init__(
        self,
        config: StudioConfig,
        project: Project,
        spec: Spec,
    ) -> None:
        self._config = config
        self._project = project
        self._spec = spec
        self._harness: Any = None
        self._session_id: str | None = None
        self._system_prompt_text: str = ""

    def start_session(self, session_id: str | None = None) -> str:
        """Build harness 并绑定 session。"""
        if session_id is None:
            session_id = self._project.create_session()
        elif session_id not in self._project.meta.get("sessions", []):
            self._project.meta.setdefault("sessions", []).append(session_id)
            self._project._save_meta()

        self._project.set_active_session(session_id)
        self._session_id = session_id
        self._build_harness()
        return session_id

    def _build_harness(self) -> None:
        """Build harness with current spec/prompt/tools/session."""
        import senza

        # ── Provider ────────────────────────────────────────
        try:
            provider = _create_provider(self._config)
        except Exception as e:
            print(f"Warning: provider setup failed: {e}", file=sys.stderr)
            raise

        # ── Execution env ───────────────────────────────────
        working_dir = str(self._project.path)
        env = senza.create_os_env(working_dir)

        # ── System prompt (dynamic) ─────────────────────────
        self._system_prompt_text = build_system_prompt(self._spec, self._project)

        # ── Build harness ───────────────────────────────────
        builder = (
            senza.HarnessBuilder(self._config.model)
            .provider("*", provider)
            .system_prompt(self._system_prompt_text)
            .env(env)
            # File tools (read/write for write_document etc.)
            .plugin(senza.create_fs_tools_plugin())
            # Strategy plugins
            .plugin(senza.strategy.safety_defaults())
            .plugin(senza.strategy.loop_safety())
            .plugin(senza.strategy.tool_output_guard(env))
            .plugin(senza.strategy.injection_filter())
            # Studio spec/doc/prefab tools
            .tools(make_spec_tools(self._spec))
            .tools(make_doc_tools(self._project))
            .tools(make_prefab_tools())
            .auto_compact(True)
            .retry(3, 1000)
        )

        # ── Session persistence ─────────────────────────────
        if self._session_id:
            try:
                ensure_session(self._project.sessions_dir, self._session_id)
                repo = senza.knowledge.jsonl_session_repo(
                    str(self._project.sessions_dir)
                )
                builder = builder.session_repo(repo, self._session_id)
            except Exception as e:
                print(f"Warning: session_repo setup failed: {e}", file=sys.stderr)

        # ── Build ───────────────────────────────────────────
        self._harness = builder.build()

    def prompt(self, text: str, timeout_ms: int = 30000) -> list[dict]:
        """Send prompt and collect events until settled.

        Returns list of event dicts. Raises RuntimeError on LLM errors.
        """
        if self._harness is None:
            raise RuntimeError("Harness not started. Call start_session() first.")
        return self._harness.prompt_and_collect(text, timeout_ms=timeout_ms)

    def subscribe(self):
        """Return event receiver for streaming. Call before prompt()."""
        if self._harness is None:
            raise RuntimeError("Harness not started. Call start_session() first.")
        return self._harness.subscribe()

    def abort(self) -> None:
        """Cancel current prompt if running."""
        if self._harness is not None:
            self._harness.abort()

    def rebuild(self) -> None:
        """Rebuild harness with current spec/prompt. Preserves session_id."""
        if self._session_id is None:
            raise RuntimeError("No session. Call start_session() first.")
        self._build_harness()
