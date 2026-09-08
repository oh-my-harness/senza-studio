"""Spec 数据模型 CRUD 测试。"""
import pytest
from studio_backend.spec import Spec, SpecError


def test_empty_spec_validate_fails():
    """空 spec（无 stages）validate 应失败。"""
    spec = Spec()
    with pytest.raises(SpecError, match="no stages"):
        spec.validate()


def test_add_step():
    spec = Spec()
    spec.add_step("classify", "分类步骤", "agent", prompt_template="分类：{input}")
    data = spec.get_current_spec()
    assert len(data["stages"]) == 1
    assert data["stages"][0]["name"] == "classify"
    assert data["stages"][0]["type"] == "agent"


def test_add_step_duplicate_name_fails():
    spec = Spec()
    spec.add_step("classify", "分类", "agent")
    with pytest.raises(SpecError, match="already exists"):
        spec.add_step("classify", "重复", "agent")


def test_add_step_invalid_type_fails():
    spec = Spec()
    with pytest.raises(SpecError, match="invalid step type"):
        spec.add_step("x", "x", "invalid_type")


def test_add_edge():
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    spec.add_step("b", "step b", "agent")
    spec.add_edge("a", "b", "success")
    data = spec.get_current_spec()
    assert data["stages"][0].get("next_on_success") == "b"


def test_add_edge_unknown_from_fails():
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    with pytest.raises(SpecError, match="not found"):
        spec.add_edge("unknown", "a", "success")


def test_add_edge_unknown_to_fails():
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    with pytest.raises(SpecError, match="not found"):
        spec.add_edge("a", "ghost", "success")


def test_remove_step():
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    spec.add_step("b", "step b", "agent")
    spec.add_edge("a", "b", "success")
    spec.remove_step("a")
    data = spec.get_current_spec()
    assert len(data["stages"]) == 1
    assert data["stages"][0]["name"] == "b"
    # edges to removed step should be cleaned
    assert "next_on_success" not in data["stages"][0]


def test_remove_step_not_found_fails():
    spec = Spec()
    with pytest.raises(SpecError, match="not found"):
        spec.remove_step("ghost")
def test_remove_step_cleans_inbound_edges():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    spec.add_step("b", "b", "agent")
    spec.add_step("c", "c", "terminal")
    spec.add_edge("b", "a", "success")  # b→a edge
    spec.add_edge("a", "c", "success")
    spec.remove_step("a")
    data = spec.get_current_spec()
    # b's edge to a should be cleaned
    assert "next_on_success" not in data["stages"][0]


def test_set_step_property():
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    spec.set_step_property("a", "output_key", "result_a")
    data = spec.get_current_spec()
    assert data["stages"][0]["output_key"] == "result_a"


def test_set_step_property_step_not_found_fails():
    spec = Spec()
    with pytest.raises(SpecError, match="not found"):
        spec.set_step_property("ghost", "key", "val")


def test_validate_no_terminal_fails():
    """有 step 但没有 terminal step → validate 失败。"""
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    with pytest.raises(SpecError, match="no terminal"):
        spec.validate()


def test_validate_passes_with_terminal():
    """有 step + terminal → validate 通过。"""
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    spec.add_step("b", "step b", "terminal")
    spec.add_edge("a", "b", "success")
    spec.validate()  # should not raise


def test_validate_dangling_edge():
    """edge 指向不存在的 step → validate 失败。"""
    spec = Spec()
    spec.add_step("a", "step a", "agent", next_on_success="ghost")
    spec.add_step("b", "step b", "terminal")
    with pytest.raises(SpecError, match="ghost"):
        spec.validate()


def test_to_yaml_and_from_yaml():
    spec = Spec()
    spec.add_step("a", "step a", "agent", prompt_template="hello")
    spec.add_step("b", "step b", "terminal", message="done")
    spec.add_edge("a", "b", "success")
    yaml_str = spec.to_yaml()
    spec2 = Spec.from_yaml(yaml_str)
    data = spec2.get_current_spec()
    assert len(data["stages"]) == 2
    assert data["stages"][0]["name"] == "a"
    assert data["stages"][1]["name"] == "b"


def test_get_current_spec_returns_deep_copy():
    """get_current_spec 返回深拷贝，修改返回值不影响原 spec。"""
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    data = spec.get_current_spec()
    data["stages"][0]["name"] = "modified"
    data2 = spec.get_current_spec()
    assert data2["stages"][0]["name"] == "a"


# ── 能力组件引用 ─────────────────────────────────────────


def test_add_component_creates_a_reference_step():
    spec = Spec()
    spec.add_component("gate", "approval_flow", params={"title": "退货审批"})
    step = spec.get_current_spec()["stages"][0]
    assert step == {
        "name": "gate",
        "component": "approval_flow",
        "params": {"title": "退货审批"},
    }


def test_add_component_without_params_omits_the_key():
    spec = Spec()
    spec.add_component("gate", "approval_flow")
    assert "params" not in spec.get_current_spec()["stages"][0]


def test_add_component_rejects_empty_names():
    spec = Spec()
    with pytest.raises(SpecError):
        spec.add_component("", "approval_flow")
    with pytest.raises(SpecError):
        spec.add_component("gate", "")


def test_add_component_rejects_duplicate_step_name():
    spec = Spec()
    spec.add_step("gate", "d", "agent")
    with pytest.raises(SpecError, match="already exists"):
        spec.add_component("gate", "approval_flow")


def test_edges_can_point_at_and_from_a_component_step():
    spec = Spec()
    spec.add_step("start", "d", "agent")
    spec.add_component("gate", "approval_flow")
    spec.add_step("done", "d", "terminal")
    spec.add_edge("start", "gate", "success")
    spec.add_edge("gate", "done", "approve")
    spec.validate()  # 不该因为 gate 没有 type 就报错


def test_validate_rejects_step_with_neither_type_nor_component():
    """既没 type 也没 component 的 step 要在校验阶段就拦下——放过去的话，
    Play 到这一步才在 executor 里报 unknown step type，那时已经跑掉几步了。"""
    spec = Spec({"stages": [
        {"name": "broken", "next_on_success": "done"},
        {"name": "done", "type": "terminal"},
    ]})
    with pytest.raises(SpecError, match="no valid type"):
        spec.validate()
