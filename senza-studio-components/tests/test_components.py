"""能力组件定义的结构测试。

这里只测"定义本身自洽"——展开逻辑在 Studio 侧（studio_backend/preprocess.py），
它的测试在 senza-studio 的 tests/test_preprocess.py。分开是因为组件包刻意
不认识 Studio 的 spec 语义，只提供数据。
"""
from __future__ import annotations

import re

import pytest

from senza_studio_components import registry
from senza_studio_components.components import approval_flow, approval_with_notice

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

ALL_COMPONENTS = [approval_flow.COMPONENT, approval_with_notice.COMPONENT]


def _strings(value):
    """递归收集定义里所有字符串，用来检查占位符。"""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


@pytest.mark.parametrize("component", ALL_COMPONENTS, ids=lambda c: c["name"])
def test_component_has_required_keys(component):
    for key in ("name", "description", "params", "steps", "edges", "ports"):
        assert key in component, f"{component['name']} 缺少 {key}"
    assert component["steps"], "组件至少要有一个 step"
    assert "entry" in component["ports"]
    assert component["ports"].get("exits"), "组件至少要有一个出口"


@pytest.mark.parametrize("component", ALL_COMPONENTS, ids=lambda c: c["name"])
def test_ports_reference_real_internal_steps(component):
    """entry 和每个 exit 都必须指向组件自己定义的 step——写错的话展开时才
    报错，而那时候用户已经在 Play 了。"""
    step_names = {s["name"] for s in component["steps"]}
    assert component["ports"]["entry"] in step_names
    for port, spec in component["ports"]["exits"].items():
        assert spec["step"] in step_names, f"出口 {port} 指向未知 step"
        assert spec.get("condition"), f"出口 {port} 没有 condition"


@pytest.mark.parametrize("component", ALL_COMPONENTS, ids=lambda c: c["name"])
def test_internal_edges_reference_real_steps(component):
    step_names = {s["name"] for s in component["steps"]}
    for edge in component["edges"]:
        assert edge["from"] in step_names
        assert edge["to"] in step_names
        assert edge.get("condition")


@pytest.mark.parametrize("component", ALL_COMPONENTS, ids=lambda c: c["name"])
def test_placeholders_are_declared_params_or_prefix(component):
    """定义里出现的每个 {name} 占位符要么是 {prefix}，要么是声明过的参数。

    拼错参数名是最难发现的错：预处理器只替换认识的名字，不认识的原样保留，
    于是 step 里会留下一个字面量 "{titel}"，展开不报错、Play 也不报错，只是
    审批界面上显示一句乱码。
    """
    allowed = {"prefix"} | set(component["params"])
    for text in _strings(component):
        for match in _PLACEHOLDER_RE.finditer(text):
            # {{var}} 是运行时 context 变量，不归组件参数管
            start = match.start()
            if start > 0 and text[start - 1] == "{":
                continue
            assert match.group(1) in allowed, (
                f"{component['name']} 里的占位符 {{{match.group(1)}}} "
                f"既不是 prefix 也不是声明过的参数"
            )


@pytest.mark.parametrize("component", ALL_COMPONENTS, ids=lambda c: c["name"])
def test_internal_step_names_are_prefixed(component):
    """内部 step 名必须带 {prefix}——否则同一个组件用两次就会撞名。"""
    for step in component["steps"]:
        assert "{prefix}" in step["name"], f"{step['name']} 没带 {{prefix}}"


def test_approval_flow_uses_checker_and_approval_form():
    """审批门的两个硬性约定：checker 类型 + approval_form 展示。Studio 的
    submit_decision 把人工决定原样当 route_key，所以出口必须叫 approve/reject。"""
    step = approval_flow.COMPONENT["steps"][0]
    assert step["type"] == "checker"
    assert step["ui"]["display"] == "approval_form"
    assert set(approval_flow.COMPONENT["ports"]["exits"]) == {"approve", "reject"}


def test_approval_with_notice_exits_from_different_steps():
    """approve 走完邮件那一步才算完，reject 直接从审批那一步出去——出口挂在
    不同内部 step 上正是 ports.exits 存在的理由。"""
    exits = approval_with_notice.COMPONENT["ports"]["exits"]
    assert exits["approve"]["step"] == "{prefix}_notify"
    assert exits["reject"]["step"] == "{prefix}_review"


def test_approval_with_notice_binds_the_send_email_prefab():
    """组件引用的工具必须真的在预制件库里，否则展开后 Play 会找不到工具。"""
    notify = approval_with_notice.COMPONENT["steps"][1]
    assert notify["tool"] in registry.get_tools()


# ── registry 层 ──────────────────────────────────────────


def test_get_components_returns_all_by_name():
    components = registry.get_components()
    assert set(components) == {"approval_flow", "approval_with_notice"}
    assert registry.get_component("approval_flow")["name"] == "approval_flow"
    assert registry.get_component("nope") is None


def test_list_prefabs_returns_both_families():
    result = registry.list_prefabs()
    assert {t["name"] for t in result["tools"]} == {
        "db_query",
        "lookup_topic",
        "send_email",
    }
    assert {c["name"] for c in result["components"]} == {
        "approval_flow",
        "approval_with_notice",
    }


def test_list_prefabs_kind_filter():
    assert registry.list_prefabs("tool")["components"] == []
    assert registry.list_prefabs("component")["tools"] == []
    assert registry.list_prefabs("component")["components"]


def test_component_projection_hides_expansion_details():
    """元 agent 只需要知道组件干什么、要填什么、有哪些出口——steps/edges/ports
    是预处理器的事，塞给模型只会浪费 context 还诱导它自己去展开。"""
    component = registry.list_prefabs("component")["components"][0]
    assert set(component) == {"name", "kind", "description", "params", "ports"}
    assert component["kind"] == "component"
    assert isinstance(component["ports"], list)


def test_search_and_recommend_span_components():
    assert "approval_flow" in {c["name"] for c in registry.search_prefabs("approval")}
    ranked = registry.recommend_prefabs("a human needs to approve this before continuing")
    assert ranked
    assert ranked[0]["kind"] == "component"
