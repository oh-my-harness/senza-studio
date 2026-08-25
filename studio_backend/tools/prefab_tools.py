"""预制件工具——Phase 1 返回空列表占位。Phase 4 填充。

Senza 的 Rust-backed Tool 对象不暴露 ``.callback`` 属性，因此回调闭包
单独由 :func:`make_prefab_callbacks` 产出，:func:`make_prefab_tools`
仅负责将它们包装成 Tool 列表。
"""
from __future__ import annotations

import json
from typing import Any, Callable

import senza


def make_prefab_callbacks() -> dict[str, Callable[[dict, Any], str]]:
    """返回 ``{tool_name: callback}`` ——预制件工具回调。Phase 1 全返回空。"""
    callbacks: dict[str, Callable[[dict, Any], str]] = {}

    def _list_prefabs(args, ctx):
        return json.dumps({"tools": [], "components": []}, ensure_ascii=False)

    callbacks["list_prefabs"] = _list_prefabs

    def _search_prefabs(args, ctx):
        return json.dumps([], ensure_ascii=False)

    callbacks["search_prefabs"] = _search_prefabs

    def _recommend_prefabs(args, ctx):
        return json.dumps([], ensure_ascii=False)

    callbacks["recommend_prefabs"] = _recommend_prefabs

    return callbacks


_SCHEMAS: dict[str, dict] = {
    "list_prefabs": {
        "description": (
            "List available prefab tools and components. "
            "Returns empty in Phase 1."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["tool", "component", "all"]},
            },
        },
    },
    "search_prefabs": {
        "description": "Search prefabs by keyword. Returns empty in Phase 1.",
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
            "Recommend prefabs based on a requirement description. "
            "Returns empty in Phase 1."
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
    """创建预制件工具列表。Phase 1 返回空结果占位。"""
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
