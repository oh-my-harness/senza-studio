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
from .session import ensure_session, session_dir_path
from .spec import Spec
from .system_prompt import build_system_prompt
from .tools.spec_tools import make_spec_tools
from .tools.doc_tools import make_doc_tools
from .tools.gen_tools import make_gen_tools
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
        """准备目标 session/harness，成功后才提交活动 session。

        旧实现先写 meta.active_session 再 build；build/恢复失败时内存里
        的 _session_id 已指向新 session，而 _harness 还是旧对象，下一次
        prompt 会写进错误的 session。这里改为 build 使用局部候选，全部
        成功后才一次性提交 meta + 内存状态。
        """
        add = session_id is None
        if session_id is None:
            session_id = self._project.new_session_id()
        else:
            # 先把非法/越界的 sid 挡在 meta 之外；ensure_session 在 build
            # 时还会再校验一次。
            session_dir_path(self._project.sessions_dir, session_id)
            add = session_id not in self._project.meta.get("sessions", [])

        harness, prompt_text = self._build_harness_for(session_id)
        # 提交点：meta 写盘成功才替换活动状态。失败时 _harness/_session_id
        # 和 project.meta 都保持旧值（commit_session 会恢复 meta）。
        self._project.commit_session(session_id, add=add)
        self._harness = harness
        self._system_prompt_text = prompt_text
        self._session_id = session_id
        return session_id

    def _build_harness_for(self, session_id: str) -> tuple[Any, str]:
        """构建候选 harness，不修改 self/project 的任何活动状态。"""
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
        prompt_text = build_system_prompt(self._spec, self._project)

        # ── Build harness ───────────────────────────────────
        builder = (
            senza.HarnessBuilder(self._config.model)
            .provider("*", provider)
            .system_prompt(prompt_text)
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
            .tools(make_gen_tools(self._project))
            .auto_compact(True)
            .retry(3, 1000)
        )

        # ── Session persistence ─────────────────────────────
        # 持久化失败不能静默降级成内存会话：那会让 UI 显示 sid 已创建、
        # /messages 却永远为空，重启后历史全丢。让异常带上上下文冒到调用方，
        # 由 WS/REST 层给用户明确错误。
        try:
            ensure_session(self._project.sessions_dir, session_id)
            repo = senza.knowledge.jsonl_session_repo(
                str(self._project.sessions_dir)
            )
            builder = builder.session_repo(repo, session_id)
        except Exception as exc:
            raise RuntimeError(
                f"session persistence unavailable for {session_id}: {exc}"
            ) from exc

        # ── Build ───────────────────────────────────────────
        return builder.build(), prompt_text

    def prompt(self, text: str, timeout_ms: int = 30000) -> list[dict]:
        """Send prompt and collect events until settled.

        Returns list of event dicts. Raises RuntimeError on LLM errors.
        """
        if self._harness is None:
            raise RuntimeError("Harness not started. Call start_session() first.")
        return self._harness.prompt_and_collect(text, timeout_ms=timeout_ms)

    def events(self, timeout_ms: int = 5000, max_consecutive_timeouts: int = 999):
        """Return event iterator for streaming. Call before prompt().

        Uses harness.events() which returns a sync iterator.
        timeout_ms is per-next() wait; max_consecutive_timeouts is high
        to avoid premature termination during LLM first-token latency.
        """
        if self._harness is None:
            raise RuntimeError("Harness not started. Call start_session() first.")
        return self._harness.events(
            timeout_ms=timeout_ms, max_consecutive_timeouts=max_consecutive_timeouts
        )

    def abort(self) -> None:
        """Cancel current prompt if running."""
        if self._harness is not None:
            self._harness.abort()

    def rebuild(self) -> None:
        """Rebuild harness with current spec/prompt. Preserves session_id."""
        if self._session_id is None:
            raise RuntimeError("No session. Call start_session() first.")
        harness, prompt_text = self._build_harness_for(self._session_id)
        self._harness = harness
        self._system_prompt_text = prompt_text
