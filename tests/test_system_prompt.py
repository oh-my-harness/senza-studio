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
