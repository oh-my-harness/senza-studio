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
