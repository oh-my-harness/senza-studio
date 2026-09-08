"""Capability components — reusable workflow fragments.

A component is a named group of steps + internal edges that a spec can
reference by name (``component: approval_flow``) instead of hand-wiring
every step. The Studio preprocessor expands the reference into real steps
before the spec is compiled; see ``COMPONENT_SCHEMA`` below for the shape
each definition must follow.
"""
from __future__ import annotations

from . import approval_flow, approval_with_notice

__all__ = ["approval_flow", "approval_with_notice", "COMPONENT_SCHEMA"]

# 文档性质的说明，给读代码的人和写新组件的人看——不是运行时校验用的
# JSON Schema（真正的校验在 Studio 的 preprocess.py 里，因为那里才知道
# 一次具体展开缺了哪个参数、撞了哪个名字）。
COMPONENT_SCHEMA = """
COMPONENT = {
    "name":        str,   # 组件名，spec 里 `component: <name>` 引用它
    "description": str,   # 给元 agent 看的一句话说明
    "params": {           # 展开时可填的参数
        "<param>": {"type": str, "description": str, "default": Any (可选)},
    },                    # 没有 default 的参数就是必填
    "steps": [ {...} ],   # 内部 step，字段跟普通 spec step 一样
    "edges": [ {"from": str, "to": str, "condition": str} ],   # 内部连线
    "ports": {
        "entry": str,     # 外部指进来的边落到哪个内部 step
        "exits": {        # 外部 next_on_<port> 接到哪个内部 step 的哪条路由
            "<port>": {"step": str, "condition": str},
        },
    },
}

steps/edges/ports 里的字符串可以用 {prefix} 占位组件实例名，用
{<param>} 占位参数值。只替换这些认识的名字，其它花括号原样保留——
prompt_template 里经常自带 JSON 例子，不能当成格式串解析。
"""
