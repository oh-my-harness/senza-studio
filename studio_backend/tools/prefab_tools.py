"""预制件工具——list/search/recommend 从 senza_studio_components 包读取真实内容。

Senza 的 Rust-backed Tool 对象不暴露 ``.callback`` 属性，因此回调闭包
单独由 :func:`make_prefab_callbacks` 产出，:func:`make_prefab_tools`
仅负责将它们包装成 Tool 列表。

senza_studio_components 住在本仓库的 ./senza-studio-components 子目录里，
但它是个自带 pyproject.toml 的独立 pip 包（Phase 7 导出的项目 pip install
它就能脱离 Studio 独立运行），所以这里当外部依赖处理：没装的话不该让整个
元 agent harness 构建失败——降级成空列表，跟 Phase 1 的占位行为一致，只是
现在"没内容"和"没装包"是两种不同原因。
"""
from __future__ import annotations

import json
from typing import Any, Callable

import senza

try:
    from senza_studio_components import registry as _prefab_registry
except ImportError:
    _prefab_registry = None


def make_prefab_callbacks() -> dict[str, Callable[[dict, Any], str]]:
    """返回 ``{tool_name: callback}`` ——预制件工具回调，读 senza_studio_components
    的真实内容；包没装时降级成空列表（不报错，元 agent 就是暂时没有预制件可推荐）。"""
    callbacks: dict[str, Callable[[dict, Any], str]] = {}

    def _list_prefabs(args, ctx):
        if _prefab_registry is None:
            return json.dumps({"tools": [], "components": []}, ensure_ascii=False)
        return json.dumps(_prefab_registry.list_prefabs(args.get("kind")), ensure_ascii=False)

    callbacks["list_prefabs"] = _list_prefabs

    def _search_prefabs(args, ctx):
        if _prefab_registry is None:
            return json.dumps([], ensure_ascii=False)
        return json.dumps(_prefab_registry.search_prefabs(args["query"]), ensure_ascii=False)

    callbacks["search_prefabs"] = _search_prefabs

    def _recommend_prefabs(args, ctx):
        if _prefab_registry is None:
            return json.dumps([], ensure_ascii=False)
        return json.dumps(_prefab_registry.recommend_prefabs(args["description"]), ensure_ascii=False)

    callbacks["recommend_prefabs"] = _recommend_prefabs

    return callbacks


_SCHEMAS: dict[str, dict] = {
    "list_prefabs": {
        "description": "List available prefab tools and components.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["tool", "component", "all"]},
            },
        },
    },
    "search_prefabs": {
        "description": "Search prefabs by keyword (matches name and description).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    "recommend_prefabs": {
        "description": (
            "Recommend prefabs based on a requirement description "
            "(ranked by keyword overlap with each prefab's description)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
            },
            "required": ["description"],
        },
    },
}


def make_prefab_tools() -> list:
    """创建预制件工具列表。"""
    callbacks = make_prefab_callbacks()
    tools = []
    for name, cb in callbacks.items():
        schema = _SCHEMAS[name]
        tools.append(
            senza.create_tool(
                name=name,
                description=schema["description"],
                parameters=schema["parameters"],
                callback=cb,
            )
        )
    return tools
