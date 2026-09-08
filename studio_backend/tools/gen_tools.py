"""定制工具生成——元 agent 写代码，Studio 负责校验、落盘（Phase 5）。

工厂模式与 spec_tools/prefab_tools 一致：回调闭包由 :func:`make_gen_callbacks`
产出（方便直接单测），:func:`make_gen_tools` 只负责包成 Tool 列表。

代码由元 agent 自己写：它本来就是个会写 Python 的 LLM，再在 Studio 里套一层
LLM 生成代码只是多花一次钱、多一份要维护的 prompt。Studio 这边只做校验 + 落
盘，校验失败就把精确错误还给它自己改——跟 validate_spec 现在的回路一模一样。
"""
from __future__ import annotations

import json
from typing import Any, Callable

import senza

from ..project import Project
from ..toolgen import MAX_ATTEMPTS, is_valid_tool_name, stub_source, validate_tool_source


def make_gen_callbacks(project: Project) -> dict[str, Callable[[dict, Any], str]]:
    """返回 ``{tool_name: callback}``——绑定到某个 project 的生成工具回调。"""
    # 每个工具名连续失败了几次。放在闭包里（跟着 StudioAgent 的生命周期），
    # 不落盘：这是"这一轮对话里试了几次"的临时状态，重启后从头再来才是对的。
    attempts: dict[str, int] = {}

    def _generate_tool(args, ctx):
        name = str(args.get("name") or "")
        description = str(args.get("description") or "")
        code = str(args.get("code") or "")

        if not code.strip():
            return "Error: code 不能为空——请把工具的完整 Python 实现传进来"

        result = validate_tool_source(name, code)
        if result.ok:
            attempts.pop(name, None)
            target = project.path / "tools" / "generated" / f"{name}.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code, encoding="utf-8")
            return (
                f"工具 '{name}' 已通过校验并写入 tools/generated/{name}.py。"
                f"现在可以用 bind_tool(step, \"{name}\") 绑到某个 tool step 上，"
                f"下一次 Play 就会加载它（不用重启）。"
            )

        # 名字本身不合法时不计次、也永远不写文件：这个名字会直接当文件名用，
        # 落 stub 等于按模型给的路径写文件（"../../x" 之类）。让它先把名字改对。
        if not is_valid_tool_name(name):
            return f"Error: {result.error}"

        attempts[name] = attempts.get(name, 0) + 1
        if attempts[name] >= MAX_ATTEMPTS:
            attempts.pop(name, None)
            target = project.path / "tools" / "generated" / f"{name}.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                stub_source(name, description or name, result.error or ""),
                encoding="utf-8",
            )
            return (
                f"Error: '{name}' 连续 {MAX_ATTEMPTS} 次没通过校验，已写入一个占位"
                f"实现 tools/generated/{name}.py 并标记为 stub，需要人工补充。"
                f"最后一次的错误：{result.error}。"
                f"请告诉用户这个工具需要开发人员手工实现，不要再重复生成。"
            )

        remaining = MAX_ATTEMPTS - attempts[name]
        return (
            f"Error: {result.error}\n"
            f"（第 {attempts[name]} 次尝试，还可以再试 {remaining} 次；"
            f"改完之后用同样的 name 再调一次 generate_tool）"
        )

    def _list_generated_tools(args, ctx):
        """让元 agent 能看到自己已经生成过什么——不然同一轮对话里很容易重复
        生成，或者忘了某个工具已经落成 stub 又去 bind_tool。"""
        directory = project.path / "tools" / "generated"
        if not directory.is_dir():
            return json.dumps([], ensure_ascii=False)
        names = sorted(
            p.stem for p in directory.glob("*.py") if not p.name.startswith("_")
        )
        return json.dumps(names, ensure_ascii=False)

    return {
        "generate_tool": _generate_tool,
        "list_generated_tools": _list_generated_tools,
    }


_SCHEMAS: dict[str, dict] = {
    "generate_tool": {
        "description": (
            "Write a custom Python tool for this project, validate it, and save it "
            "to tools/generated/<name>.py. Use this ONLY after list_prefabs / "
            "search_prefabs / recommend_prefabs show that no existing prefab tool "
            "covers the need.\n\n"
            "You write the code yourself and pass it in `code`. The module must "
            "define a TOOL dict:\n\n"
            "  def fetch_order(args):\n"
            "      return {\"status\": \"shipped\"}   # dict or str\n\n"
            "  TOOL = {\n"
            "      \"name\": \"fetch_order\",\n"
            "      \"description\": \"Look up an order by id\",\n"
            "      \"parameters\": {\"type\": \"object\",\n"
            "                     \"properties\": {\"order_id\": {\"type\": \"string\"}},\n"
            "                     \"required\": [\"order_id\"]},\n"
            "      \"callback\": fetch_order,\n"
            "  }\n\n"
            "Rules: TOOL['name'] must equal `name`; the name must be lower_snake_case; "
            "do real work inside the callback, never at module top level (the module "
            "is imported during validation and a blocking top-level call will time "
            "out); prefer the standard library, since a third-party import fails "
            "validation unless it is already installed. If validation fails you get "
            "the exact error back — fix the code and call again with the same name."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Tool name, lower_snake_case; also the filename",
                },
                "description": {
                    "type": "string",
                    "description": "What the tool does, for whoever binds it later",
                },
                "code": {
                    "type": "string",
                    "description": "Complete Python source of the module, defining TOOL",
                },
            },
            "required": ["name", "description", "code"],
        },
    },
    "list_generated_tools": {
        "description": (
            "List the custom tools already generated for this project, so you do "
            "not regenerate one that exists."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


def make_gen_tools(project: Project) -> list:
    """创建绑定到 project 的定制工具生成工具列表。"""
    callbacks = make_gen_callbacks(project)
    return [
        senza.create_tool(
            name=name,
            description=_SCHEMAS[name]["description"],
            parameters=_SCHEMAS[name]["parameters"],
            callback=callback,
        )
        for name, callback in callbacks.items()
    ]
