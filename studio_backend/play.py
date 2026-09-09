"""Play 模式——实现已搬到 senza_studio_runtime（Phase 7）。

这一层只做两件事：

1. **转发**运行时那些本来就与 Studio 无关的函数（executor/judge/模板渲染/
   工具与插件加载），保留 ``studio_backend.play`` 这个导入路径；
2. **翻译** Studio 的类型：运行时只认根目录 + spec dict + 模型名 + provider，
   Project/StudioConfig → 这四个参数的转换发生在这里。

为什么实现要搬走：Phase 7 的验收标准是"导出项目行为和 Studio 里一致"。做到这
一点唯一可靠的办法是两边跑**同一份**代码——各留一份拷贝的话漂移只是时间问题，
而且这种漂移很隐蔽（Play 一个样、导出后另一个样，要跑起来才看得见）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from senza_studio_runtime import play as _runtime

# ── 与 Studio 无关，直接转发 ────────────────────────────
from senza_studio_runtime.play import (  # noqa: F401
    PENDING_APPROVAL,
    build_route_maps,
    decision_context_key,
    get_entry_inputs,
    make_executor,
    make_judge,
    render_prompt_template,
    render_tool_args,
    # 下面这几个是内部helper，转发出来是为了让现有单测继续按原路径 import
    # ——它们本来就在直接测这些小函数（模板渲染的边界、工具返回值归一化
    # 之类），换个 import 路径没有任何收益。
    _append_routing_instruction,
    _call_tool,
    _extract_json_fields,
    _normalize_tool_result,
)

from .config import StudioConfig
from .project import Project
from .spec import Spec

__all__ = [
    "PENDING_APPROVAL",
    "PlaySession",
    "build_route_maps",
    "decision_context_key",
    "get_entry_inputs",
    "load_project_plugins",
    "load_tool_registry",
    "make_executor",
    "make_judge",
    "render_prompt_template",
    "render_tool_args",
]


def _create_provider(config: StudioConfig) -> Any:
    """保留这个名字：Studio 里已有调用点（agent.py 另有一份自己的）。"""
    return _runtime.create_provider(config.api_key, config.api_base)


def load_tool_registry(project: Project) -> tuple[dict[str, Callable], str | None]:
    """按 Project 加载工具。实现见 senza_studio_runtime.play.load_tool_registry
    ——运行时收的是根目录，这里只负责把 Project 翻成路径。"""
    return _runtime.load_tool_registry(project.path)


def load_project_plugins(project: Project) -> tuple[list[Any], list[str]]:
    """按 Project 加载插件集。实现见 senza_studio_runtime.play。"""
    return _runtime.load_project_plugins(project.path)


class PlaySession(_runtime.PlaySession):
    """Studio 侧的 PlaySession：把 Project/StudioConfig 翻成运行时的入参，
    并额外做 Studio 自己的记账（项目 meta 里的 status）。

    记账留在这一层而不是下沉进运行时：导出的项目没有 meta.json，也没有"项目
    状态"这个概念，那是 Studio 的项目列表要用的东西。
    """

    def __init__(self, config: StudioConfig, project: Project, spec: Spec) -> None:
        # 只存引用，什么都不读——和重构前一致的惰性。构造之后、Play 之前
        # 改的 spec 也要能生效，所以 spec 的快照必须发生在 play() 那一刻，
        # 不能在这里。（现有单测也依赖这一点：它们用 PlaySession(None,
        # None, None) 单独测 pause/resume/step 的状态机。）
        super().__init__()
        self._config = config
        self._project = project
        self._spec = spec

    def play(self, inputs: dict[str, str] | None = None, start_paused: bool = False) -> None:
        # Studio 类型 → 运行时入参，就在这一刻翻译
        self._root = Path(self._project.path)
        self._spec_dict = self._spec.get_current_spec()
        self._model = self._config.model
        self._provider = _create_provider(self._config)

        super().play(inputs=inputs, start_paused=start_paused)

        self._project.meta["status"] = "playing"
        self._project._save_meta()
