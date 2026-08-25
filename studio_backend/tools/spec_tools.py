"""Spec 构建工具——元 agent 通过这些工具增量构建 spec。

每个工具是一个闭包，绑定到 Spec 实例。
工具回调不抛异常——捕获 SpecError 返回错误字符串。

Senza 的 Rust-backed Tool 对象不暴露 ``.callback`` 属性，因此回调闭包
单独由 :func:`make_spec_callbacks` 产出，:func:`make_spec_tools` 仅负责
将它们包装成 Tool 列表。测试直接调用回调闭包验证行为。
"""
from __future__ import annotations

import json
from typing import Any, Callable

import senza

from ..spec import Spec, SpecError


def make_spec_callbacks(spec: Spec) -> dict[str, Callable[[dict, Any], str]]:
    """返回 ``{tool_name: callback}`` ——绑定到 spec 实例的回调闭包。

    回调签名 ``(args: dict, ctx: Any) -> str``，永不抛 SpecError，
    而是返回 ``"Error: ..."`` 字符串。
    """
    callbacks: dict[str, Callable[[dict, Any], str]] = {}

    def _add_step(args, ctx):
        try:
            spec.add_step(
                name=args["name"],
                description=args.get("description", ""),
                type=args["type"],
                prompt_template=args.get("prompt_template"),
            )
            return f"Step '{args['name']}' added."
        except SpecError as e:
            return f"Error: {e}"

    callbacks["add_step"] = _add_step

    def _add_edge(args, ctx):
        try:
            spec.add_edge(
                from_step=args["from"],
                to_step=args["to"],
                condition=args["condition"],
            )
            return f"Edge {args['from']} --{args['condition']}--> {args['to']} added."
        except SpecError as e:
            return f"Error: {e}"

    callbacks["add_edge"] = _add_edge

    def _remove_step(args, ctx):
        try:
            spec.remove_step(args["name"])
            return f"Step '{args['name']}' removed."
        except SpecError as e:
            return f"Error: {e}"

    callbacks["remove_step"] = _remove_step

    def _remove_edge(args, ctx):
        try:
            spec.remove_edge(
                from_step=args["from"],
                to_step=args["to"],
                condition=args["condition"],
            )
            return "Edge removed."
        except SpecError as e:
            return f"Error: {e}"

    callbacks["remove_edge"] = _remove_edge

    def _set_step_property(args, ctx):
        try:
            spec.set_step_property(
                step_name=args["step"],
                key=args["key"],
                value=args["value"],
            )
            return f"Property '{args['key']}' set on '{args['step']}'."
        except SpecError as e:
            return f"Error: {e}"

    callbacks["set_step_property"] = _set_step_property

    def _bind_tool(args, ctx):
        try:
            spec.set_step_property(args["step"], "tool", args["tool_ref"])
            return f"Tool '{args['tool_ref']}' bound to '{args['step']}'."
        except SpecError as e:
            return f"Error: {e}"

    callbacks["bind_tool"] = _bind_tool

    def _set_ui_config(args, ctx):
        try:
            ui: dict[str, Any] = {"display": args["display"]}
            if args.get("fields"):
                ui["fields"] = args["fields"]
            spec.set_step_property(args["step"], "ui", ui)
            return f"UI config set on '{args['step']}'."
        except SpecError as e:
            return f"Error: {e}"

    callbacks["set_ui_config"] = _set_ui_config

    def _get_current_spec(args, ctx):
        return json.dumps(spec.get_current_spec(), ensure_ascii=False, indent=2)

    callbacks["get_current_spec"] = _get_current_spec

    def _validate_spec(args, ctx):
        try:
            spec.validate()
            return "Spec is valid."
        except SpecError as e:
            return f"Validation error: {e}"

    callbacks["validate_spec"] = _validate_spec

    return callbacks


# ── Tool schema 定义 ──────────────────────────────────────

_SCHEMAS: dict[str, dict] = {
    "add_step": {
        "description": (
            "Add a step to the spec. type must be one of: "
            "agent, checker, tool, terminal."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique step name"},
                "description": {"type": "string", "description": "Step description"},
                "type": {
                    "type": "string",
                    "enum": ["agent", "checker", "tool", "terminal"],
                    "description": "Step type",
                },
                "prompt_template": {
                    "type": "string",
                    "description": "Prompt template for agent steps",
                },
            },
            "required": ["name", "description", "type"],
        },
    },
    "add_edge": {
        "description": "Add an edge (transition) between two steps with a condition.",
        "parameters": {
            "type": "object",
            "properties": {
                "from": {"type": "string", "description": "Source step name"},
                "to": {"type": "string", "description": "Target step name"},
                "condition": {
                    "type": "string",
                    "description": "Condition name (e.g. success, reject)",
                },
            },
            "required": ["from", "to", "condition"],
        },
    },
    "remove_step": {
        "description": (
            "Remove a step from the spec. Edges pointing to it are cleaned up."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Step name to remove"},
            },
            "required": ["name"],
        },
    },
    "remove_edge": {
        "description": "Remove an edge between two steps.",
        "parameters": {
            "type": "object",
            "properties": {
                "from": {"type": "string"},
                "to": {"type": "string"},
                "condition": {"type": "string"},
            },
            "required": ["from", "to", "condition"],
        },
    },
    "set_step_property": {
        "description": "Set an arbitrary property on a step.",
        "parameters": {
            "type": "object",
            "properties": {
                "step": {"type": "string", "description": "Step name"},
                "key": {"type": "string", "description": "Property key"},
                "value": {"description": "Property value (any JSON type)"},
            },
            "required": ["step", "key", "value"],
        },
    },
    "bind_tool": {
        "description": "Bind a prefab tool to a step.",
        "parameters": {
            "type": "object",
            "properties": {
                "step": {"type": "string", "description": "Step name"},
                "tool_ref": {
                    "type": "string",
                    "description": "Tool name from prefab registry",
                },
            },
            "required": ["step", "tool_ref"],
        },
    },
    "set_ui_config": {
        "description": (
            "Set the UI display config for a step. "
            "display: chat/status/table/chart/approval_form/none."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "step": {"type": "string"},
                "display": {
                    "type": "string",
                    "enum": [
                        "chat",
                        "status",
                        "table",
                        "chart",
                        "approval_form",
                        "none",
                    ],
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional field names to display",
                },
            },
            "required": ["step", "display"],
        },
    },
    "get_current_spec": {
        "description": (
            "Get the current spec as JSON. Use this to review the spec "
            "before making changes."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    "validate_spec": {
        "description": (
            "Validate the spec for completeness. "
            "Checks edges, terminal steps, etc."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


def make_spec_tools(spec: Spec) -> list:
    """创建绑定到 spec 实例的 spec 构建工具列表。

    返回 Senza ``Tool`` 对象列表。回调闭包由
    :func:`make_spec_callbacks` 产出，便于直接测试。
    """
    callbacks = make_spec_callbacks(spec)
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
