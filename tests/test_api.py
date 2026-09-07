"""REST API + WebSocket 端点测试。"""
import pytest
from fastapi.testclient import TestClient

from studio_backend.app import create_app, _reset_state
from studio_backend.config import StudioConfig


@pytest.fixture
def app_client(tmp_path):
    _reset_state()
    config = StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test-model",
        api_key="test-key",
        api_base="",
    )
    app = create_app(config)
    with TestClient(app) as client:
        yield client
    _reset_state()


# ── Health ──────────────────────────────────────────────


def test_health(app_client):
    r = app_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── Settings ────────────────────────────────────────────


def test_get_settings_returns_schema_and_empty_values(app_client):
    r = app_client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    keys = {item["key"] for item in body["schema"]}
    assert "SENZA_SMTP_HOST" in keys
    assert "SENZA_SMTP_PASSWORD" in keys
    assert body["values"] == {}


def test_get_settings_returns_sections_matching_field_groups(app_client):
    """设置面板左侧导航按 group 分区——每个字段的 group 都该有对应说明，
    否则前端会渲染出一个没有说明的分区。"""
    body = app_client.get("/api/settings").json()
    assert "邮件" in body["sections"]
    field_groups = {item["group"] for item in body["schema"]}
    assert field_groups <= set(body["sections"]), "every field group needs a section entry"


def test_put_settings_saves_and_get_returns_them(app_client):
    r = app_client.put(
        "/api/settings",
        json={"values": {"SENZA_SMTP_HOST": "smtp.example.com"}},
    )
    assert r.status_code == 200
    body = app_client.get("/api/settings").json()
    assert body["values"]["SENZA_SMTP_HOST"] == "smtp.example.com"


def test_get_settings_never_returns_plaintext_secret(app_client):
    """密钥不该出现在 HTTP 响应里（浏览器 devtools/前端内存）。"""
    app_client.put(
        "/api/settings", json={"values": {"SENZA_SMTP_PASSWORD": "hunter2"}}
    )
    body = app_client.get("/api/settings").json()
    assert "hunter2" not in r_text(body)
    assert body["values"]["SENZA_SMTP_PASSWORD"] != "hunter2"


def r_text(obj) -> str:
    import json as _json

    return _json.dumps(obj)


# ── Projects ────────────────────────────────────────────


def test_list_projects_empty(app_client):
    r = app_client.get("/api/projects")
    assert r.status_code == 200
    assert r.json() == []


def test_create_project(app_client):
    r = app_client.post("/api/projects", json={"name": "测试项目"})
    assert r.status_code == 200
    data = r.json()
    assert "id" in data
    assert data["name"] == "测试项目"


def test_create_project_missing_name(app_client):
    r = app_client.post("/api/projects", json={})
    assert r.status_code == 422


def test_get_project(app_client):
    r = app_client.post("/api/projects", json={"name": "项目A"})
    pid = r.json()["id"]
    r = app_client.get(f"/api/projects/{pid}")
    assert r.status_code == 200
    assert r.json()["name"] == "项目A"
    assert r.json()["id"] == pid


def test_get_project_not_found(app_client):
    r = app_client.get("/api/projects/nonexistent")
    assert r.status_code == 404


def test_list_projects_after_create(app_client):
    app_client.post("/api/projects", json={"name": "项目A"})
    app_client.post("/api/projects", json={"name": "项目B"})
    r = app_client.get("/api/projects")
    assert len(r.json()) == 2


def test_delete_project(app_client):
    r = app_client.post("/api/projects", json={"name": "测试"})
    pid = r.json()["id"]
    r = app_client.delete(f"/api/projects/{pid}")
    assert r.status_code == 200
    r = app_client.get(f"/api/projects/{pid}")
    assert r.status_code == 404
    r = app_client.get("/api/projects")
    assert r.json() == []


def test_delete_project_not_found(app_client):
    r = app_client.delete("/api/projects/nonexistent")
    assert r.status_code == 404


def test_delete_project_clears_cache(app_client):
    """先 GET 把项目载入 _studio_state 缓存，再删——缓存也要清掉。"""
    r = app_client.post("/api/projects", json={"name": "测试"})
    pid = r.json()["id"]
    app_client.get(f"/api/projects/{pid}")  # 载入缓存
    r = app_client.delete(f"/api/projects/{pid}")
    assert r.status_code == 200
    r = app_client.get(f"/api/projects/{pid}")
    assert r.status_code == 404


# ── Spec ────────────────────────────────────────────────


def test_get_spec(app_client):
    r = app_client.post("/api/projects", json={"name": "测试"})
    pid = r.json()["id"]
    r = app_client.get(f"/api/projects/{pid}/spec")
    assert r.status_code == 200
    data = r.json()
    assert "stages" in data
    assert data["stages"] == []


def test_update_spec(app_client):
    r = app_client.post("/api/projects", json={"name": "测试"})
    pid = r.json()["id"]
    new_spec = {
        "stages": [
            {"name": "step1", "type": "terminal", "message": "done"}
        ]
    }
    r = app_client.put(
        f"/api/projects/{pid}/spec", json={"spec": new_spec}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    # 验证 spec 已更新
    r = app_client.get(f"/api/projects/{pid}/spec")
    data = r.json()
    assert len(data["stages"]) == 1
    assert data["stages"][0]["name"] == "step1"


def test_update_spec_wrapper_key(app_client):
    """前端 api.ts updateSpec 发送 {"spec": spec} 包装。"""
    r = app_client.post("/api/projects", json={"name": "测试"})
    pid = r.json()["id"]
    new_spec = {"stages": [{"name": "s", "type": "terminal", "message": "x"}]}
    r = app_client.put(
        f"/api/projects/{pid}/spec", json={"spec": new_spec}
    )
    assert r.status_code == 200


# ── Sessions ────────────────────────────────────────────


def test_list_sessions_empty(app_client):
    r = app_client.post("/api/projects", json={"name": "测试"})
    pid = r.json()["id"]
    r = app_client.get(f"/api/projects/{pid}/sessions")
    assert r.status_code == 200
    data = r.json()
    assert data["sessions"] == []
    assert data["active"] is None


def test_create_session(app_client):
    r = app_client.post("/api/projects", json={"name": "测试"})
    pid = r.json()["id"]
    r = app_client.post(f"/api/projects/{pid}/sessions")
    assert r.status_code == 200
    assert "session_id" in r.json()


def test_list_sessions_after_create(app_client):
    r = app_client.post("/api/projects", json={"name": "测试"})
    pid = r.json()["id"]
    app_client.post(f"/api/projects/{pid}/sessions")
    r = app_client.get(f"/api/projects/{pid}/sessions")
    assert len(r.json()["sessions"]) == 1


# ── WebSocket ───────────────────────────────────────────


def test_ws_connection(app_client):
    """WebSocket 能连接并接收消息。"""
    r = app_client.post("/api/projects", json={"name": "测试"})
    pid = r.json()["id"]
    with app_client.websocket_connect(f"/ws/projects/{pid}") as ws:
        # 发送 abort 消息（不需要 LLM）
        ws.send_json({"type": "abort"})
        # 连接保持，无异常即可


def test_ws_switch_session(app_client):
    """WebSocket switch_session 消息切换 session。"""
    r = app_client.post("/api/projects", json={"name": "测试"})
    pid = r.json()["id"]
    # 先创建一个 session
    r = app_client.post(f"/api/projects/{pid}/sessions")
    sid = r.json()["session_id"]
    with app_client.websocket_connect(f"/ws/projects/{pid}") as ws:
        ws.send_json({"type": "switch_session", "session_id": sid})
        msg = ws.receive_json()
        assert msg["type"] == "session_switched"
        assert msg["session_id"] == sid
