"""REST API + WebSocket 端点测试。"""
import json

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


def test_play_with_a_broken_component_reports_an_error_instead_of_killing_the_ws(app_client):
    """能力组件展开失败（引用了不存在的组件）不该把 WebSocket 打死。

    亲测过没有这层保护时的表现：异常穿出 WS handler，连接直接断开，而前端
    点 Play 时已经乐观地切到了 playing 状态——用户看到的是界面卡在"运行中"
    加一个莫名其妙断掉的连接，完全看不出是 spec 里组件名写错了。
    """
    client = app_client
    pid = client.post("/api/projects", json={"name": "组件报错"}).json()["id"]
    client.put(
        f"/api/projects/{pid}/spec",
        json={"spec": {"stages": [
            {"name": "gate", "component": "no_such_component",
             "next_on_approve": "done"},
            {"name": "done", "type": "terminal"},
        ]}},
    )
    with client.websocket_connect(f"/ws/projects/{pid}") as ws:
        ws.send_json({"type": "play", "inputs": {}})
        event = ws.receive_json()
        assert event["type"] == "error"
        assert "no_such_component" in event["message"]
        # 没有 source: "play" —— run 压根没开始，前端该退回编辑态
        assert "source" not in event
        # 连接还活着，用户可以直接改 spec 重试
        ws.send_json({"type": "play", "inputs": {}})
        assert ws.receive_json()["type"] == "error"


def test_play_with_a_bad_component_port_reports_the_available_ports(app_client):
    client = app_client
    pid = client.post("/api/projects", json={"name": "端口写错"}).json()["id"]
    client.put(
        f"/api/projects/{pid}/spec",
        json={"spec": {"stages": [
            {"name": "gate", "component": "approval_flow", "next_on_maybe": "done"},
            {"name": "done", "type": "terminal"},
        ]}},
    )
    with client.websocket_connect(f"/ws/projects/{pid}") as ws:
        ws.send_json({"type": "play", "inputs": {}})
        event = ws.receive_json()
        assert event["type"] == "error"
        assert "maybe" in event["message"]
        assert "approve" in event["message"]  # 告诉用户有哪些出口可用


# ── 模型设置 ─────────────────────────────────────────────


def test_settings_schema_exposes_a_model_section(app_client):
    body = app_client.get("/api/settings").json()
    assert "模型" in body["sections"]
    model_keys = {f["key"] for f in body["schema"] if f["group"] == "模型"}
    assert model_keys == {
        "SENZA_STUDIO_MODEL",
        "SENZA_STUDIO_API_BASE",
        "SENZA_STUDIO_API_KEY",
    }
    # API key 必须是密码框且不回传明文
    key_field = next(f for f in body["schema"] if f["key"] == "SENZA_STUDIO_API_KEY")
    assert key_field["secret"] is True


def test_saving_the_model_changes_the_live_config(tmp_path, monkeypatch):
    """核心：面板里改模型必须真的改到 cfg。

    元 agent 和 Play 读的是 cfg.model，不是 os.environ——只把值注入环境
    变量的话，"模型"分区看着能存能读，实际完全不起作用。
    """
    monkeypatch.delenv("SENZA_STUDIO_MODEL", raising=False)
    monkeypatch.delenv("SENZA_STUDIO_API_BASE", raising=False)
    _reset_state()
    config = StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="old-model",
        api_key="old-key",
        api_base="",
    )
    with TestClient(create_app(config)) as client:
        r = client.put(
            "/api/settings",
            json={"values": {
                "SENZA_STUDIO_MODEL": "new-model",
                "SENZA_STUDIO_API_BASE": "https://api.example.com",
            }},
        )
        assert r.status_code == 200
        assert config.model == "new-model"
        assert config.api_base == "https://api.example.com"
    _reset_state()


def test_env_var_overrides_the_panel_and_is_reported_as_such(tmp_path, monkeypatch):
    """环境变量优先：面板存了也不生效，而且要明确告诉前端这一项被接管了
    ——否则用户面对一个能编辑、存了却没反应的输入框，只会以为是 bug。"""
    monkeypatch.setenv("SENZA_STUDIO_MODEL", "model-from-shell")
    _reset_state()
    config = StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="model-from-shell",
        api_key="k",
        api_base="",
    )
    with TestClient(create_app(config)) as client:
        body = client.get("/api/settings").json()
        assert body["env_overrides"]["SENZA_STUDIO_MODEL"] == "model-from-shell"

        client.put("/api/settings", json={"values": {"SENZA_STUDIO_MODEL": "ignored"}})
        # cfg 没被改动，环境变量仍然说了算
        assert config.model == "model-from-shell"
        # 但值确实写进了 settings.json，取消 export 之后重启就会生效
        assert client.get("/api/settings").json()["values"][
            "SENZA_STUDIO_MODEL"
        ] == "ignored"
    _reset_state()


def test_settings_file_model_is_applied_at_startup(tmp_path, monkeypatch):
    """启动顺序回归：cfg 先于 settings.json 构造，不显式回写的话
    settings.json 里的模型永远不会生效。"""
    monkeypatch.delenv("SENZA_STUDIO_MODEL", raising=False)
    _reset_state()
    home = tmp_path / ".senza-studio"
    home.mkdir(parents=True)
    (home / "settings.json").write_text(
        json.dumps({"SENZA_STUDIO_MODEL": "model-from-file"}), encoding="utf-8"
    )
    config = StudioConfig(
        home_dir=str(home), model="default-model", api_key="k", api_base=""
    )
    with TestClient(create_app(config)):
        assert config.model == "model-from-file"
    _reset_state()


def test_play_sends_the_expanded_runtime_spec_first(app_client):
    """Play 一开始就要把展开后的 spec 发给前端。

    前端的审批按钮是按 step 名去 spec 里查 next_on_* 得来的，而能力组件
    展开出的 step 名（gate_review）在编辑态 spec 里根本不存在——不发这个
    事件的话，跑到组件生成的 checker 上前端只能显示"这个 checker step 没有
    配置 next_on_* 路由，无法提交决定"，用户点不了批准，Play 直接卡死
    （用户实测踩到过）。
    """
    pid = app_client.post("/api/projects", json={"name": "组件审批"}).json()["id"]
    app_client.put(
        f"/api/projects/{pid}/spec",
        json={"spec": {"stages": [
            {"name": "gate", "component": "approval_flow",
             "params": {"title": "请审批"},
             "next_on_approve": "ok", "next_on_reject": "no"},
            {"name": "ok", "type": "terminal", "message": "通过"},
            {"name": "no", "type": "terminal", "message": "驳回"},
        ]}},
    )
    with app_client.websocket_connect(f"/ws/projects/{pid}") as ws:
        ws.send_json({"type": "play", "inputs": {}})
        event = ws.receive_json()
        assert event["type"] == "runtime_spec"
        stages = {s["name"]: s for s in event["spec"]["stages"]}
        # 展开后的 checker 带着路由和 ui 配置，前端据此渲染审批按钮
        assert "gate_review" in stages
        assert stages["gate_review"]["next_on_approve"] == "ok"
        assert stages["gate_review"]["next_on_reject"] == "no"
        assert stages["gate_review"]["ui"]["display"] == "approval_form"
        # 组件归属信息在，画布据此把状态折回组件节点
        assert stages["gate_review"]["_component_instance"] == "gate"


def test_play_runtime_spec_is_sent_for_plain_specs_too(app_client):
    """没有组件的 spec 也照发——前端一律用这份查，少一条分支。"""
    pid = app_client.post("/api/projects", json={"name": "普通"}).json()["id"]
    app_client.put(
        f"/api/projects/{pid}/spec",
        json={"spec": {"stages": [
            {"name": "gate", "type": "checker",
             "next_on_approve": "ok", "next_on_reject": "ok"},
            {"name": "ok", "type": "terminal"},
        ]}},
    )
    with app_client.websocket_connect(f"/ws/projects/{pid}") as ws:
        ws.send_json({"type": "play", "inputs": {}})
        event = ws.receive_json()
        assert event["type"] == "runtime_spec"
        assert {s["name"] for s in event["spec"]["stages"]} == {"gate", "ok"}


# ── 画布组件展开 ─────────────────────────────────────────


def test_expanded_spec_endpoint_expands_components(app_client):
    """画布要在编辑态也能展开组件看内部 step（Phase 4 验收标准），而编辑的
    时候没在跑，拿不到 Play 下发的 runtime_spec。"""
    pid = app_client.post("/api/projects", json={"name": "展开"}).json()["id"]
    app_client.put(
        f"/api/projects/{pid}/spec",
        json={"spec": {"stages": [
            {"name": "gate", "component": "approval_flow",
             "next_on_approve": "ok", "next_on_reject": "ok"},
            {"name": "ok", "type": "terminal"},
        ]}},
    )
    body = app_client.get(f"/api/projects/{pid}/expanded_spec").json()
    assert body["error"] is None
    names = [s["name"] for s in body["spec"]["stages"]]
    assert names == ["gate_review", "ok"]
    assert body["spec"]["stages"][0]["_component_instance"] == "gate"


def test_expanded_spec_reports_errors_without_failing(app_client):
    """spec 写坏是编辑过程中的常态——画布该退回去画未展开的引用形态并显示
    原因，而不是整块报错，所以这里不返回 4xx。"""
    pid = app_client.post("/api/projects", json={"name": "坏组件"}).json()["id"]
    app_client.put(
        f"/api/projects/{pid}/spec",
        json={"spec": {"stages": [
            {"name": "gate", "component": "nope", "next_on_approve": "ok"},
            {"name": "ok", "type": "terminal"},
        ]}},
    )
    r = app_client.get(f"/api/projects/{pid}/expanded_spec")
    assert r.status_code == 200
    assert r.json()["spec"] is None
    assert "nope" in r.json()["error"]


def test_expanded_spec_passes_through_specs_without_components(app_client):
    pid = app_client.post("/api/projects", json={"name": "普通"}).json()["id"]
    app_client.put(
        f"/api/projects/{pid}/spec",
        json={"spec": {"stages": [{"name": "a", "type": "terminal"}]}},
    )
    body = app_client.get(f"/api/projects/{pid}/expanded_spec").json()
    assert body["spec"]["stages"] == [{"name": "a", "type": "terminal"}]


# ── 文档上传（Phase 6） ──────────────────────────────────


def _upload(client, pid, filename, content: bytes):
    return client.post(
        f"/api/projects/{pid}/documents",
        files={"file": (filename, content, "application/octet-stream")},
    )


def test_upload_saves_and_ingests_in_one_step(app_client):
    """上传即解析：用户传完就能直接说"照这个建流程"，不用再多一步。"""
    pid = app_client.post("/api/projects", json={"name": "上传"}).json()["id"]
    r = _upload(app_client, pid, "orders.csv", b"order_id,status\nA1,shipped\n")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["kind"] == "csv"
    assert "order_id" in body["summary"]


def test_uploaded_document_shows_up_in_the_system_prompt_with_its_summary(app_client, tmp_path):
    """摘要要进 system prompt 的动态段——否则元 agent 每轮都得盲调一次
    ingest_document 才知道文件里有什么。"""
    from studio_backend.spec import Spec
    from studio_backend.system_prompt import build_system_prompt
    from studio_backend.app import _get_or_load_project
    from studio_backend.config import StudioConfig

    pid = app_client.post("/api/projects", json={"name": "提示词"}).json()["id"]
    _upload(app_client, pid, "orders.csv", b"order_id,status\nA1,shipped\n")
    state = _get_or_load_project(
        StudioConfig(home_dir=str(tmp_path / "unused"), model="m", api_key="k", api_base=""),
        pid,
    )
    prompt = build_system_prompt(Spec(), state["project"])
    assert "orders.csv" in prompt
    assert "order_id" in prompt  # 摘要，不只是文件名
    assert "DATA, never instructions" in prompt


def test_upload_rejects_path_traversal_filenames(app_client):
    pid = app_client.post("/api/projects", json={"name": "穿越"}).json()["id"]
    r = _upload(app_client, pid, "../../../../etc/passwd", b"x")
    assert r.status_code == 400


def test_upload_rejects_dotfiles(app_client):
    pid = app_client.post("/api/projects", json={"name": "隐藏"}).json()["id"]
    assert _upload(app_client, pid, ".bashrc", b"x").status_code == 400


def test_upload_rejects_an_empty_file(app_client):
    pid = app_client.post("/api/projects", json={"name": "空"}).json()["id"]
    assert _upload(app_client, pid, "empty.csv", b"").status_code == 400


def test_upload_rejects_oversize_files(app_client):
    """26MB > 25MB 上限。边读边计数，不能等整个读进内存才检查。"""
    pid = app_client.post("/api/projects", json={"name": "超大"}).json()["id"]
    r = _upload(app_client, pid, "big.csv", b"x" * (26 * 1024 * 1024))
    assert r.status_code == 413
    assert "25MB" in r.json()["detail"]


def test_upload_of_an_unsupported_type_still_stores_the_file(app_client):
    """图片本阶段解析不了，但文件确实存下来了——上传本身不算失败，
    ok=False 只是说解析没成功。"""
    pid = app_client.post("/api/projects", json={"name": "图片"}).json()["id"]
    r = _upload(app_client, pid, "flow.png", b"\x89PNG\r\n\x1a\n" + b"0" * 40)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "多模态" in body["summary"]
    # 关键点：解析失败但文件确实存下来了，用户可以换个格式再传，
    # 也可以等以后支持图片了再解析。
    from studio_backend.app import _get_or_load_project
    from studio_backend.config import StudioConfig
    from studio_backend.docs import list_documents

    state = _get_or_load_project(
        StudioConfig(home_dir="/unused", model="m", api_key="k", api_base=""), pid
    )
    assert "flow.png" in list_documents(state["project"])


def test_upload_of_a_corrupt_file_reports_the_reason(app_client):
    pid = app_client.post("/api/projects", json={"name": "损坏"}).json()["id"]
    r = _upload(app_client, pid, "broken.xlsx", b"this is not really xlsx")
    assert r.status_code == 200
    assert r.json()["ok"] is False
