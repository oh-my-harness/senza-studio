"""Spec 预处理器（能力组件展开）测试。

大部分用例注入一个手写的假组件，而不是用 senza-studio-components 里的真
组件——测的是展开逻辑本身（端口改写、参数替换、错误处理），不该因为真组件
改了个默认值就红。末尾另有几个用例专门跑真组件，确认两边接得上。
"""
from __future__ import annotations

import pytest

from studio_backend.preprocess import (
    PreprocessError,
    expand_component,
    preprocess_spec,
)


FAKE = {
    "name": "fake_gate",
    "description": "测试用组件",
    "params": {
        "title": {"type": "string", "default": "默认标题"},
        "target": {"type": "string"},  # 无默认 => 必填
    },
    "steps": [
        {"name": "{prefix}_review", "type": "checker", "message": "{title}"},
        {"name": "{prefix}_notify", "type": "tool", "tool": "send_email",
         "tool_args": {"to": "{target}"}},
    ],
    "edges": [
        {"from": "{prefix}_review", "to": "{prefix}_notify", "condition": "approve"},
    ],
    "ports": {
        "entry": "{prefix}_review",
        "exits": {
            "approve": {"step": "{prefix}_notify", "condition": "success"},
            "reject": {"step": "{prefix}_review", "condition": "reject"},
        },
    },
}
COMPONENTS = {"fake_gate": FAKE}


def _spec(**gate_extra):
    gate = {"name": "gate", "component": "fake_gate",
            "params": {"target": "ops@example.com"}}
    gate.update(gate_extra)
    return {
        "stages": [
            {"name": "start", "type": "agent", "prompt_template": "hi",
             "next_on_success": "gate"},
            gate,
            {"name": "done", "type": "terminal", "message": "bye"},
        ]
    }


def _by_name(spec):
    return {s["name"]: s for s in spec["stages"]}


# ── 无组件时的行为 ────────────────────────────────────────


def test_spec_without_components_is_unchanged():
    spec = {"stages": [{"name": "a", "type": "agent"}]}
    assert preprocess_spec(spec) == spec


def test_preprocess_does_not_mutate_input():
    """展开必须返回新 dict——调用方拿到的是 Spec 的当前状态，就地改会污染
    编辑态 spec，画布下一次读就会看到展开后的 step。"""
    spec = _spec(next_on_approve="done", next_on_reject="done")
    before = str(spec)
    preprocess_spec(spec, COMPONENTS)
    assert str(spec) == before


# ── 展开本身 ──────────────────────────────────────────────


def test_component_expands_into_its_steps():
    out = preprocess_spec(_spec(next_on_approve="done", next_on_reject="done"), COMPONENTS)
    names = [s["name"] for s in out["stages"]]
    assert names == ["start", "gate_review", "gate_notify", "done"]
    assert "gate" not in names  # 引用本身消失了


def test_generated_steps_carry_component_metadata():
    """画布画 group 容器全靠这两个字段。"""
    out = preprocess_spec(_spec(next_on_approve="done", next_on_reject="done"), COMPONENTS)
    for name in ("gate_review", "gate_notify"):
        step = _by_name(out)[name]
        assert step["_component"] == "fake_gate"
        assert step["_component_instance"] == "gate"
    assert "_component" not in _by_name(out)["start"]


def test_incoming_edge_is_rewired_to_entry_port():
    out = preprocess_spec(_spec(next_on_approve="done", next_on_reject="done"), COMPONENTS)
    assert _by_name(out)["start"]["next_on_success"] == "gate_review"


def test_internal_edges_are_materialized():
    out = preprocess_spec(_spec(next_on_approve="done", next_on_reject="done"), COMPONENTS)
    assert _by_name(out)["gate_review"]["next_on_approve"] == "gate_notify"


def test_exit_ports_map_to_the_declared_internal_step():
    """approve 出口挂在 _notify 上、reject 出口挂在 _review 上——出口来自
    不同内部 step 正是 ports.exits 存在的理由。"""
    out = preprocess_spec(
        _spec(next_on_approve="done", next_on_reject="start"), COMPONENTS
    )
    steps = _by_name(out)
    assert steps["gate_notify"]["next_on_success"] == "done"
    assert steps["gate_review"]["next_on_reject"] == "start"


def test_entry_step_is_placed_first_when_component_is_the_entry_stage():
    """stages_to_workflow 把第一个 stage 当入口。组件正好排第一时，展开后
    的顺序必须让入口 step 仍然排第一，否则整个 workflow 从错的地方开始。"""
    spec = {
        "stages": [
            {"name": "gate", "component": "fake_gate",
             "params": {"target": "x@example.com"}, "next_on_approve": "done"},
            {"name": "done", "type": "terminal"},
        ]
    }
    out = preprocess_spec(spec, COMPONENTS)
    assert out["stages"][0]["name"] == "gate_review"


# ── 参数 ──────────────────────────────────────────────────


def test_params_are_substituted_and_defaults_applied():
    out = preprocess_spec(
        _spec(next_on_approve="done", next_on_reject="done"), COMPONENTS
    )
    steps = _by_name(out)
    assert steps["gate_review"]["message"] == "默认标题"       # 用了默认值
    assert steps["gate_notify"]["tool_args"]["to"] == "ops@example.com"


def test_explicit_param_overrides_default():
    spec = _spec(next_on_approve="done", next_on_reject="done")
    spec["stages"][1]["params"] = {"target": "a@b.c", "title": "退货审批"}
    out = preprocess_spec(spec, COMPONENTS)
    assert _by_name(out)["gate_review"]["message"] == "退货审批"


def test_runtime_double_brace_placeholders_survive_expansion():
    """{{var}} 是 Play 时才替换的 context 变量，预处理阶段必须原样留着。
    占位符正则要是把 {{order_id}} 的内层当组件参数吃掉，运行时就再也拿不到
    这个变量了。"""
    spec = _spec(next_on_approve="done", next_on_reject="done")
    spec["stages"][1]["params"] = {"target": "{{customer_email}}"}
    out = preprocess_spec(spec, COMPONENTS)
    assert _by_name(out)["gate_notify"]["tool_args"]["to"] == "{{customer_email}}"


def test_missing_required_param_is_an_error():
    spec = _spec(next_on_approve="done")
    spec["stages"][1]["params"] = {}
    with pytest.raises(PreprocessError, match="必填参数"):
        preprocess_spec(spec, COMPONENTS)


def test_unknown_param_is_an_error_not_silently_ignored():
    """参数名拼错静默忽略的话，组件照常展开、只是用了默认值，要跑到 Play
    里看到不对的行为才发现。"""
    spec = _spec(next_on_approve="done")
    spec["stages"][1]["params"] = {"target": "x", "titel": "拼错了"}
    with pytest.raises(PreprocessError, match="titel"):
        preprocess_spec(spec, COMPONENTS)


def test_non_dict_params_is_an_error():
    spec = _spec(next_on_approve="done")
    spec["stages"][1]["params"] = "title=x"
    with pytest.raises(PreprocessError, match="params 必须是 dict"):
        preprocess_spec(spec, COMPONENTS)


# ── 错误处理 ──────────────────────────────────────────────


def test_unknown_component_is_an_error_listing_what_is_available():
    spec = _spec(next_on_approve="done")
    spec["stages"][1]["component"] = "no_such_component"
    with pytest.raises(PreprocessError, match="fake_gate"):
        preprocess_spec(spec, COMPONENTS)


def test_unknown_exit_port_is_an_error():
    """spec 写了 next_on_maybe，但组件只有 approve/reject——不报错的话这条边
    会被静默丢掉，Play 到那一步才发现无路可走。"""
    spec = _spec(next_on_maybe="done")
    with pytest.raises(PreprocessError, match="出口 'maybe'"):
        preprocess_spec(spec, COMPONENTS)


def test_name_collision_with_an_existing_step_is_an_error():
    """组件实例叫 gate，展开出 gate_review；spec 里已经有个手写的 gate_review
    就撞了。不检查的话后一个会静默覆盖前一个。"""
    spec = _spec(next_on_approve="done", next_on_reject="done")
    spec["stages"].append({"name": "gate_review", "type": "terminal"})
    with pytest.raises(PreprocessError, match="重名"):
        preprocess_spec(spec, COMPONENTS)


def test_component_step_without_name_is_an_error():
    with pytest.raises(PreprocessError, match="必须有 name"):
        expand_component({"component": "fake_gate"}, FAKE)


def test_bad_entry_port_is_an_error():
    broken = {**FAKE, "ports": {**FAKE["ports"], "entry": "{prefix}_nope"}}
    with pytest.raises(PreprocessError, match="entry 端口"):
        expand_component({"name": "g", "params": {"target": "x"}}, broken)


def test_component_with_no_steps_is_an_error():
    broken = {**FAKE, "steps": []}
    with pytest.raises(PreprocessError, match="没有定义任何 step"):
        expand_component({"name": "g", "params": {"target": "x"}}, broken)


# ── 多实例 / 组件互连 ─────────────────────────────────────


def test_same_component_can_be_instantiated_twice():
    """内部 step 名带 {prefix}，所以同一个组件用两次不会撞名。"""
    spec = {
        "stages": [
            {"name": "first", "component": "fake_gate",
             "params": {"target": "a@b.c"}, "next_on_approve": "second",
             "next_on_reject": "done"},
            {"name": "second", "component": "fake_gate",
             "params": {"target": "d@e.f"}, "next_on_approve": "done",
             "next_on_reject": "done"},
            {"name": "done", "type": "terminal"},
        ]
    }
    out = preprocess_spec(spec, COMPONENTS)
    names = [s["name"] for s in out["stages"]]
    assert names == [
        "first_review", "first_notify", "second_review", "second_notify", "done",
    ]
    # 第一个组件的 approve 出口指向第二个组件实例 => 改写成它的入口 step
    assert _by_name(out)["first_notify"]["next_on_success"] == "second_review"


def test_forward_reference_between_components_is_rewritten():
    """组件 A 的出口指向排在它后面的组件 B。改写放在全部展开之后统一做，
    就是为了不依赖 stage 顺序。"""
    spec = {
        "stages": [
            {"name": "a", "component": "fake_gate", "params": {"target": "x"},
             "next_on_approve": "b", "next_on_reject": "done"},
            {"name": "b", "component": "fake_gate", "params": {"target": "y"},
             "next_on_approve": "done", "next_on_reject": "done"},
            {"name": "done", "type": "terminal"},
        ]
    }
    out = preprocess_spec(spec, COMPONENTS)
    assert _by_name(out)["a_notify"]["next_on_success"] == "b_review"


# ── 真实组件 ──────────────────────────────────────────────


def test_real_approval_flow_expands_to_a_checker_gate():
    spec = {
        "stages": [
            {"name": "gate", "component": "approval_flow",
             "params": {"title": "退货审批"},
             "next_on_approve": "ok", "next_on_reject": "no"},
            {"name": "ok", "type": "terminal"},
            {"name": "no", "type": "terminal"},
        ]
    }
    review = _by_name(preprocess_spec(spec))["gate_review"]
    assert review["type"] == "checker"
    assert review["message"] == "退货审批"
    assert review["ui"]["display"] == "approval_form"
    assert review["next_on_approve"] == "ok"
    assert review["next_on_reject"] == "no"


def test_real_approval_with_notice_wires_email_between_approve_and_next():
    spec = {
        "stages": [
            {"name": "gate", "component": "approval_with_notice",
             "params": {"notify_to": "ops@example.com"},
             "next_on_approve": "ok", "next_on_reject": "no"},
            {"name": "ok", "type": "terminal"},
            {"name": "no", "type": "terminal"},
        ]
    }
    steps = _by_name(preprocess_spec(spec))
    assert steps["gate_review"]["next_on_approve"] == "gate_notify"
    assert steps["gate_notify"]["tool"] == "send_email"
    assert steps["gate_notify"]["tool_args"]["to"] == "ops@example.com"
    assert steps["gate_notify"]["next_on_success"] == "ok"
    assert steps["gate_review"]["next_on_reject"] == "no"


def test_missing_components_package_degrades_to_unknown_component_error(monkeypatch):
    """组件包没装时不该 ImportError 崩掉整个 Play——只有真的引用了组件的
    spec 才报错，而且报的是"未知组件"这种能看懂的话。"""
    spec = {
        "stages": [
            {"name": "gate", "component": "approval_flow", "next_on_approve": "ok"},
            {"name": "ok", "type": "terminal"},
        ]
    }
    with pytest.raises(PreprocessError, match="未知能力组件"):
        preprocess_spec(spec, components={})
