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

def test_start_session_build_failure_keeps_previous_binding(tmp_project, monkeypatch):
    old_sid = "sess-old"
    tmp_project.meta["sessions"] = [old_sid]
    tmp_project.meta["active_session"] = old_sid
    tmp_project._save_meta()
    agent = StudioAgent(tmp_project.config, tmp_project, Spec())
    old_harness = object()
    agent._harness = old_harness
    agent._session_id = old_sid

    def fail_build(session_id):
        raise RuntimeError("repo unavailable")

    monkeypatch.setattr(agent, "_build_harness_for", fail_build)
    with pytest.raises(RuntimeError, match="repo unavailable"):
        agent.start_session("sess-new")

    assert agent._harness is old_harness
    assert agent._session_id == old_sid
    assert tmp_project.meta["active_session"] == old_sid
    assert tmp_project.meta["sessions"] == [old_sid]


def test_start_session_meta_commit_failure_rolls_back_memory(tmp_project, monkeypatch):
    old_sid = "sess-old"
    tmp_project.meta["sessions"] = [old_sid]
    tmp_project.meta["active_session"] = old_sid
    tmp_project._save_meta()
    agent = StudioAgent(tmp_project.config, tmp_project, Spec())
    old_harness = object()
    agent._harness = old_harness
    agent._session_id = old_sid
    new_harness = object()

    monkeypatch.setattr(
        agent,
        "_build_harness_for",
        lambda session_id: (new_harness, "new prompt"),
    )

    def fail_save():
        raise OSError("disk full")

    monkeypatch.setattr(tmp_project, "_save_meta", fail_save)
    with pytest.raises(OSError, match="disk full"):
        agent.start_session("sess-new")

    assert agent._harness is old_harness
    assert agent._session_id == old_sid
    assert tmp_project.meta["active_session"] == old_sid
    assert tmp_project.meta["sessions"] == [old_sid]
