"""Spec 预处理器：把编辑态 spec 展开成运行态 spec。

编辑态 spec（元 agent 构建、画布展示、存盘的那份）里能力组件是**引用**：

    - name: refund_approval
      component: approval_flow
      params: {title: "退货审批"}
      next_on_approve: notify_warehouse
      next_on_reject: notify_customer

运行态 spec（喂给 stages_to_workflow 的那份）里它已经被展开成真正的 step。
保留引用而不是展开后存盘，是为了让画布能画出组件边界、让用户改一次组件
定义所有引用它的 spec 都跟着变，也让 spec 本身保持可读。

为什么在 Studio 应用层而不是 SDK：组件展开、type 语义、ui 字段都是 Studio
的概念，senza SDK 只认 stages + 边。Phase 7 导出时这个模块会挪进
senza-studio-runtime，让 Studio 和导出的项目共用同一个预处理器——所以这里
刻意不依赖 Project/StudioConfig 之类 Studio 专有的东西，入参出参都是纯 dict。
"""
from __future__ import annotations

import copy
import re
from typing import Any

_EDGE_PREFIX = "next_on_"

# 组件定义里的占位符：{prefix} 是组件实例名，{param} 是参数值。
#
# 两个分支的顺序很重要：先吃掉 {{word}} 整体并原样保留，再匹配单花括号的
# {word}。不这么写的话 "{{customer_message}}" 里的内层 {customer_message}
# 会被当成组件参数占位符——那是 prompt_template 的运行时变量，要留到 Play
# 时由 render_prompt_template 替换，预处理阶段碰它就等于把变量吃掉了。
# 同理，认识的名字才替换，其它花括号（prompt 里常见的 JSON 例子）原样保留。
_PLACEHOLDER_RE = re.compile(r"\{\{\w+\}\}|\{(\w+)\}")


class PreprocessError(Exception):
    """组件展开失败——未知组件、缺参数、端口写错、名字撞车等。"""


def _load_components() -> dict[str, dict]:
    """跟 play.py 的 _load_prefab_tools 一样防御性 import——组件包没装的话
    降级成"没有组件可用"，只有真的引用了组件的 spec 才会报错。"""
    try:
        from senza_studio_components import registry as prefab_registry
    except ImportError:
        return {}
    get_components = getattr(prefab_registry, "get_components", None)
    if get_components is None:
        return {}
    return get_components()


def _render(value: Any, subs: dict[str, Any]) -> Any:
    """递归替换字符串里的 {prefix}/{param} 占位符，dict/list 原样递归。"""
    if isinstance(value, str):
        def _sub(match: re.Match) -> str:
            key = match.group(1)
            if key is None:  # 匹配到 {{...}} 分支，原样保留
                return match.group(0)
            if key in subs:
                return str(subs[key])
            return match.group(0)

        return _PLACEHOLDER_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _render(v, subs) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, subs) for v in value]
    return value


def _resolve_params(stage: dict, definition: dict) -> dict[str, Any]:
    """合并声明的默认值和 spec 里填的 params。

    未知参数直接报错而不是忽略——参数名写错（typo）是最容易犯又最难发现的
    错：静默忽略的话组件照常展开，只是用的是默认值，要跑到 Play 里看到不对
    的行为才会发现。
    """
    declared: dict = definition.get("params", {}) or {}
    provided = stage.get("params") or {}
    if not isinstance(provided, dict):
        raise PreprocessError(
            f"step '{stage.get('name')}' 的 params 必须是 dict，"
            f"实际是 {type(provided).__name__}"
        )

    unknown = sorted(set(provided) - set(declared))
    if unknown:
        raise PreprocessError(
            f"组件 '{definition['name']}' 没有参数 {unknown}"
            f"（可用参数：{sorted(declared) or '无'}）"
        )

    values: dict[str, Any] = {}
    missing: list[str] = []
    for key, meta in declared.items():
        if key in provided:
            values[key] = provided[key]
        elif isinstance(meta, dict) and "default" in meta:
            values[key] = meta["default"]
        else:
            missing.append(key)
    if missing:
        raise PreprocessError(
            f"组件 '{definition['name']}' 缺少必填参数 {sorted(missing)}"
            f"（step '{stage.get('name')}'）"
        )
    return values


def expand_component(stage: dict, definition: dict) -> tuple[list[dict], str]:
    """展开一个组件引用，返回 (生成的 step 列表, 入口 step 名)。

    生成的 step 带 `_component`（组件名）和 `_component_instance`（实例名，
    也就是 spec 里写的那个 step 名）两个元数据字段，画布据此画 group 容器。
    下划线开头是 Studio 内部约定，stages_to_workflow 不认识这些字段，原样
    带着不影响编译。
    """
    prefix = stage.get("name")
    if not prefix:
        raise PreprocessError("引用组件的 step 必须有 name")

    subs = {"prefix": prefix, **_resolve_params(stage, definition)}
    component_name = definition["name"]

    steps: list[dict] = []
    by_name: dict[str, dict] = {}
    for template in definition.get("steps", []):
        step = _render(copy.deepcopy(template), subs)
        step["_component"] = component_name
        step["_component_instance"] = prefix
        if step["name"] in by_name:
            raise PreprocessError(
                f"组件 '{component_name}' 内部 step 重名: {step['name']}"
            )
        by_name[step["name"]] = step
        steps.append(step)
    if not steps:
        raise PreprocessError(f"组件 '{component_name}' 没有定义任何 step")

    def _internal(step_name: str, what: str) -> dict:
        target = by_name.get(step_name)
        if target is None:
            raise PreprocessError(
                f"组件 '{component_name}' 的 {what} 指向不存在的内部 step "
                f"'{step_name}'"
            )
        return target

    # 内部连线
    for edge in definition.get("edges", []):
        src = _internal(_render(edge["from"], subs), "内部边")
        dst = _render(edge["to"], subs)
        _internal(dst, "内部边")
        src[f"{_EDGE_PREFIX}{_render(edge['condition'], subs)}"] = dst

    # 外部出口：spec 里写在组件 step 上的 next_on_<port> 接到对应内部 step
    ports = definition.get("ports", {}) or {}
    exits = ports.get("exits", {}) or {}
    for key, target in stage.items():
        if not key.startswith(_EDGE_PREFIX) or not isinstance(target, str):
            continue
        port = key[len(_EDGE_PREFIX):]
        spec_exit = exits.get(port)
        if spec_exit is None:
            raise PreprocessError(
                f"组件 '{component_name}' 没有出口 '{port}'"
                f"（可用出口：{sorted(exits) or '无'}）"
            )
        src = _internal(_render(spec_exit["step"], subs), f"出口 '{port}'")
        src[f"{_EDGE_PREFIX}{_render(spec_exit['condition'], subs)}"] = target

    entry_name = _render(ports.get("entry", ""), subs)
    _internal(entry_name, "entry 端口")

    # 入口 step 排在最前面——stages_to_workflow 把第一个 stage 当 entry_step，
    # 组件正好是 spec 第一个 stage 时，展开后的顺序必须让入口仍然排第一。
    steps.sort(key=lambda s: s["name"] != entry_name)
    return steps, entry_name


def preprocess_spec(
    spec_dict: dict, components: dict[str, dict] | None = None
) -> dict:
    """编辑态 spec → 运行态 spec。没有组件引用时等价于深拷贝。

    components 参数只为测试注入用；正常调用不传，走 _load_components()。
    """
    stages = spec_dict.get("stages", [])
    if not any(isinstance(s, dict) and s.get("component") for s in stages):
        return copy.deepcopy(spec_dict)

    if components is None:
        components = _load_components()

    new_stages: list[dict] = []
    # 组件实例名 -> 入口 step 名，用来把外部指向组件的边改指到入口
    entry_by_instance: dict[str, str] = {}

    for stage in stages:
        component_name = stage.get("component") if isinstance(stage, dict) else None
        if not component_name:
            new_stages.append(copy.deepcopy(stage))
            continue
        definition = components.get(component_name)
        if definition is None:
            raise PreprocessError(
                f"未知能力组件 '{component_name}'"
                f"（step '{stage.get('name')}'；已安装的组件："
                f"{sorted(components) or '无——senza-studio-components 没装？'}）"
            )
        generated, entry = expand_component(stage, definition)
        entry_by_instance[stage["name"]] = entry
        new_stages.extend(generated)

    # 外部指向组件实例的边改指到入口 step。放在全部展开之后统一做，这样
    # 一个组件的出口指向另一个组件实例也能正确改写（否则依赖 stage 顺序）。
    for step in new_stages:
        for key, value in list(step.items()):
            if key.startswith(_EDGE_PREFIX) and isinstance(value, str):
                if value in entry_by_instance:
                    step[key] = entry_by_instance[value]

    seen: set[str] = set()
    for step in new_stages:
        name = step.get("name", "")
        if name in seen:
            raise PreprocessError(
                f"组件展开后 step 重名: '{name}'——组件实例名换一个就能避开"
            )
        seen.add(name)

    return {**copy.deepcopy(spec_dict), "stages": new_stages}
