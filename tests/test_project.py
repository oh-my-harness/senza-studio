"""项目管理测试。"""
import pytest
from studio_backend.project import Project
from studio_backend.config import StudioConfig


@pytest.fixture
def tmp_config(tmp_path):
    return StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test-model",
        api_key="test-key",
        api_base="",
    )


def test_create_project(tmp_config):
    proj = Project.create(tmp_config, "测试项目")
    assert proj.meta["name"] == "测试项目"
    assert proj.meta["status"] == "editing"
    assert proj.path.is_dir()
    assert (proj.path / "pipeline.yaml").exists()
    assert (proj.path / "tools" / "generated").is_dir()
    assert (proj.path / "tools" / "custom").is_dir()
    assert (proj.path / "tools" / "registry.py").exists()
    assert "get_tools" in (proj.path / "tools" / "registry.py").read_text()
    assert (proj.path / "plugins").is_dir()
    assert (proj.path / ".studio" / "sessions").is_dir()


def test_open_project(tmp_config):
    proj = Project.create(tmp_config, "测试")
    proj2 = Project.open(tmp_config, proj.meta["id"])
    assert proj2.meta["name"] == "测试"
    assert proj2.meta["id"] == proj.meta["id"]


def test_open_project_not_found(tmp_config):
    with pytest.raises(FileNotFoundError):
        Project.open(tmp_config, "nonexistent-id")


def test_delete_project(tmp_config):
    proj = Project.create(tmp_config, "测试")
    pid = proj.meta["id"]
    Project.delete(tmp_config, pid)
    assert not proj.path.exists()
    with pytest.raises(FileNotFoundError):
        Project.open(tmp_config, pid)


def test_delete_project_not_found(tmp_config):
    with pytest.raises(FileNotFoundError):
        Project.delete(tmp_config, "nonexistent-id")


def test_delete_project_rejects_path_traversal(tmp_config):
    with pytest.raises(FileNotFoundError):
        Project.delete(tmp_config, "../../etc")


def test_delete_project_removes_from_list(tmp_config):
    proj = Project.create(tmp_config, "测试")
    Project.delete(tmp_config, proj.meta["id"])
    assert Project.list_all(tmp_config) == []


def test_list_projects(tmp_config):
    Project.create(tmp_config, "项目A")
    Project.create(tmp_config, "项目B")
    projects = Project.list_all(tmp_config)
    assert len(projects) == 2


def test_list_projects_empty(tmp_config):
    projects = Project.list_all(tmp_config)
    assert projects == []


def test_save_and_load_spec(tmp_config):
    from studio_backend.spec import Spec
    proj = Project.create(tmp_config, "测试")
    spec = Spec()
    spec.add_step("a", "step a", "agent", prompt_template="hello")
    spec.add_step("b", "step b", "terminal", message="done")
    spec.add_edge("a", "b", "success")
    proj.save_spec(spec)
    # 重新打开
    proj2 = Project.open(tmp_config, proj.meta["id"])
    spec2 = proj2.load_spec()
    data = spec2.get_current_spec()
    assert len(data["stages"]) == 2


def test_create_session(tmp_config):
    proj = Project.create(tmp_config, "测试")
    sid = proj.create_session()
    assert sid in proj.meta["sessions"]
    assert proj.meta["active_session"] == sid


def test_switch_session(tmp_config):
    proj = Project.create(tmp_config, "测试")
    sid1 = proj.create_session()
    sid2 = proj.create_session()
    proj.set_active_session(sid1)
    assert proj.meta["active_session"] == sid1


def test_set_active_session_invalid(tmp_config):
    proj = Project.create(tmp_config, "测试")
    with pytest.raises(ValueError):
        proj.set_active_session("invalid-sid")


def test_save_updates_timestamp(tmp_config):
    proj = Project.create(tmp_config, "测试")
    old_ts = proj.meta["updated_at"]
    import time
    time.sleep(0.01)
    from studio_backend.spec import Spec
    spec = Spec()
    spec.add_step("a", "a", "terminal", message="done")
    proj.save_spec(spec)
    proj2 = Project.open(tmp_config, proj.meta["id"])
    assert proj2.meta["updated_at"] >= old_ts


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("SENZA_STUDIO_HOME", "/tmp/test-studio")
    monkeypatch.setenv("SENZA_STUDIO_MODEL", "gpt-4o")
    monkeypatch.setenv("SENZA_STUDIO_API_KEY", "sk-test")
    monkeypatch.setenv("SENZA_STUDIO_API_BASE", "https://api.test.com")
    monkeypatch.setenv(
        "SENZA_STUDIO_ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost,"
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    config = StudioConfig.from_env()
    assert config.home_dir == "/tmp/test-studio"
    assert config.model == "gpt-4o"
    assert config.api_key == "sk-test"
    assert config.api_base == "https://api.test.com"
    assert config.allowed_origins == (
        "http://localhost:5173",
        "http://localhost",
        "http://127.0.0.1:5173",
    )


def test_config_rejects_wildcard_origin(monkeypatch):
    monkeypatch.setenv("SENZA_STUDIO_ALLOWED_ORIGINS", "*")

    with pytest.raises(ValueError, match="Invalid Senza Studio browser origin"):
        StudioConfig.from_env()
