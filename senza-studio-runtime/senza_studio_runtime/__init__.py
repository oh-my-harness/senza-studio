"""Senza Studio 运行时——executor、judge、spec 预处理器。

从 Studio 后端抽出来的那一份**唯一实现**：Studio 的 Play 和导出的独立项目都
import 这个包，不各留一份拷贝。Phase 7 的验收标准是"导出项目行为和 Studio 里
一致"，只有一份代码才让这件事结构性成立——两份拷贝漂移只是时间问题。

不认识 Studio 的 Project/StudioConfig：入口只收根目录、spec dict、模型名和
provider。Studio 侧由 studio_backend/play.py 那层薄适配负责翻译。
"""
from .play import (
    PENDING_APPROVAL,
    PlaySession,
    build_route_maps,
    create_provider,
    decision_context_key,
    get_entry_inputs,
    load_project_plugins,
    load_tool_registry,
    make_executor,
    make_judge,
    render_prompt_template,
    render_tool_args,
)
from .preprocess import PreprocessError, expand_component, preprocess_spec

__all__ = [
    "PENDING_APPROVAL",
    "PlaySession",
    "PreprocessError",
    "build_route_maps",
    "create_provider",
    "decision_context_key",
    "expand_component",
    "get_entry_inputs",
    "load_project_plugins",
    "load_tool_registry",
    "make_executor",
    "make_judge",
    "preprocess_spec",
    "render_prompt_template",
    "render_tool_args",
]
