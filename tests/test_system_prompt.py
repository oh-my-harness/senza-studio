# tests/test_system_prompt.py
"""动态 system prompt 组装测试。"""
import pytest
from studio_backend.spec import Spec
from studio_backend.project import Project
from studio_backend.config import StudioConfig
from studio_backend.system_prompt import build_system_prompt


@pytest.fixture
def tmp_project(tmp_path):
    config = StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test", api_key="k", api_base="",
    )
    return Project.create(config, "测试项目")


def test_prompt_has_fixed_section(tmp_project):
    spec = Spec()
    prompt = build_system_prompt(spec, tmp_project)
    assert "Senza Studio" in prompt
    assert "spec" in prompt.lower()


def test_prompt_has_dynamic_spec_summary(tmp_project):
    spec = Spec()
    spec.add_step("classify", "分类", "agent", prompt_template="分类：{input}")
    spec.add_step("done", "完成", "terminal", message="done")
    spec.add_edge("classify", "done", "success")
    prompt = build_system_prompt(spec, tmp_project)
    assert "classify" in prompt
    assert "done" in prompt


def test_prompt_has_empty_spec_indicator(tmp_project):
    spec = Spec()
    prompt = build_system_prompt(spec, tmp_project)
    assert "empty" in prompt.lower() or "no steps" in prompt.lower()


def test_prompt_has_document_list(tmp_project):
    (tmp_project.path / ".studio" / "docs" / "design.md").write_text(
        "hi", encoding="utf-8"
    )
    spec = Spec()
    prompt = build_system_prompt(spec, tmp_project)
    assert "design.md" in prompt


def test_prompt_has_project_name(tmp_project):
    spec = Spec()
    prompt = build_system_prompt(spec, tmp_project)
    assert "测试项目" in prompt


def test_prompt_has_tool_instructions(tmp_project):
    spec = Spec()
    prompt = build_system_prompt(spec, tmp_project)
    assert "add_step" in prompt
    assert "add_edge" in prompt
    assert "validate_spec" in prompt


def test_prompt_no_longer_claims_it_cannot_generate_tools(tmp_project):
    """用户实测踩过：元 agent 说'我不能帮你写工具代码'。拦着它的不是能力，
    就是提示词里这一句话（Phase 5 之前是准确的，现在必须删掉）。"""
    prompt = build_system_prompt(Spec(), tmp_project)
    assert "cannot generate tool code" not in prompt


def test_prompt_describes_the_escalation_ladder(tmp_project):
    """预制件 → generate_tool → 人工。顺序写清楚，元 agent 才不会一上来就
    让用户自己去写代码。"""
    prompt = build_system_prompt(Spec(), tmp_project)
    assert "generate_tool" in prompt
    assert "list_generated_tools" in prompt
    for layer in ("tools/generated/", "tools/custom/", "tools/registry.py"):
        assert layer in prompt
