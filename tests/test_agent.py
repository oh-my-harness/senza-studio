"""元 agent Harness 组装测试。"""
import pytest
from studio_backend.spec import Spec
from studio_backend.project import Project
from studio_backend.config import StudioConfig
from studio_backend.agent import StudioAgent


@pytest.fixture
def tmp_project(tmp_path):
    config = StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test-model",
        api_key="test-key",
        api_base="",
    )
    return Project.create(config, "测试")


def test_studio_agent_init(tmp_project):
    """StudioAgent 初始化不 build harness（延迟到 start_session）。"""
    spec = Spec()
    agent = StudioAgent(tmp_project.config, tmp_project, spec)
    assert agent._harness is None


def test_start_session_creates_harness(tmp_project):
    """start_session 后 harness 非 None。"""
    spec = Spec()
    agent = StudioAgent(tmp_project.config, tmp_project, spec)
    session_id = agent.start_session()
    assert session_id is not None
    assert agent._harness is not None


def test_start_session_with_existing_session(tmp_project):
    """用已有 session_id 启动。"""
    spec = Spec()
    agent = StudioAgent(tmp_project.config, tmp_project, spec)
    sid = tmp_project.create_session()
    session_id = agent.start_session(sid)
    assert session_id == sid


def test_rebuild_after_spec_change(tmp_project):
    """spec 变化后 rebuild 更新 system prompt。"""
    spec = Spec()
    agent = StudioAgent(tmp_project.config, tmp_project, spec)
    agent.start_session()
    old_prompt = agent._system_prompt_text
    spec.add_step("a", "a", "terminal", message="done")
    agent.rebuild()
    new_prompt = agent._system_prompt_text
    assert old_prompt != new_prompt
    assert "a" in new_prompt


def test_rebuild_preserves_session(tmp_project):
    """rebuild 后 session_id 不变。"""
    spec = Spec()
    agent = StudioAgent(tmp_project.config, tmp_project, spec)
    sid = agent.start_session()
    agent.rebuild()
    assert agent._session_id == sid
