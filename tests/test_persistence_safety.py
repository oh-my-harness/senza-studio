"""Studio 持久化安全回归：原子写、损坏隔离、容错读取与保存反馈。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from studio_backend import settings as settings_mod
from studio_backend import storage
from studio_backend.app import (
    _get_or_load_project,
    _reset_state,
    _studio_state,
    create_app,
)
from studio_backend.config import StudioConfig
from studio_backend.project import Project, ProjectDataError
from studio_backend.session import ensure_session, read_session_history
from studio_backend.settings import load_settings, save_settings, settings_path
from studio_backend.spec import Spec

TOKEN = "a" * 40


@pytest.fixture
def cfg(tmp_path):
    return StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test-model",
        api_key="test-key",
        api_base="",
        api_token=TOKEN,
    )


@pytest.fixture
def api_client(cfg):
    _reset_state()
    app = create_app(cfg)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client
    _reset_state()


def _valid_spec():
    return Spec(
        {
            "stages": [
                {"name": "done", "type": "terminal", "message": "ok"},
            ]
        }
    )


ENTRY_1 = "0192f0aa-0000-7000-8000-000000000001"
ENTRY_2 = "0192f0aa-0000-7000-8000-000000000002"


def _runtime_entry(
    entry_id: str = ENTRY_1,
    parent_id: str | None = None,
    *,
    text: str = "hello",
    role: str = "user",
) -> dict:
    return {
        "id": entry_id,
        "parent_id": parent_id,
        "timestamp": "2026-10-27T00:00:00Z",
        "payload": {
            "entry_type": "message",
            "role": role,
            "timestamp": "2026-10-27T00:00:00Z",
            "content": [{"type": "text", "text": text}],
        },
        "compaction_policy": None,
    }


def test_atomic_write_preserves_old_file_on_replace_failure(tmp_path, monkeypatch):
    path = tmp_path / "data.json"
    path.write_text("old", encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(storage, "_replace_with_retry", boom)
    with pytest.raises(OSError):
        storage.atomic_write_text(path, "new")
    assert path.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".data.json.*.tmp"))


def test_save_spec_failure_keeps_previous_pipeline(cfg, monkeypatch):
    project = Project.create(cfg, "p")
    old = (project.path / "pipeline.yaml").read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(storage, "_replace_with_retry", boom)
    with pytest.raises(OSError):
        project.save_spec(_valid_spec())
    assert (project.path / "pipeline.yaml").read_text(encoding="utf-8") == old
    assert project.load_spec().get_current_spec() == {"stages": []}


def test_corrupt_project_meta_is_skipped_and_open_reports_error(cfg):
    good = Project.create(cfg, "good")
    bad = Project.create(cfg, "bad")
    (bad.path / ".studio" / "meta.json").write_text("", encoding="utf-8")

    listed = Project.list_all(cfg)
    assert [m["id"] for m in listed] == [good.meta["id"]]
    with pytest.raises(ProjectDataError):
        Project.open(cfg, bad.meta["id"])


def test_empty_or_malformed_pipeline_is_not_silently_accepted(cfg):
    project = Project.create(cfg, "p")
    yaml_path = project.path / "pipeline.yaml"

    yaml_path.write_text("   \n", encoding="utf-8")
    with pytest.raises(ProjectDataError):
        project.load_spec()

    yaml_path.write_text("stages:\n", encoding="utf-8")
    with pytest.raises(ProjectDataError):
        project.load_spec()

    yaml_path.write_text("stages: []\n", encoding="utf-8")
    assert project.load_spec().get_current_spec() == {"stages": []}

    for raw in (
        "null\n",
        "# only a comment\n",
        "name: no-stages\n",
        "stages: {}\n",
        "stages:\n  - null\n",
        "- just\n- a\n- list\n",
    ):
        yaml_path.write_text(raw, encoding="utf-8")
        with pytest.raises(ProjectDataError):
            project.load_spec()
        # 读取失败不能改写损坏文件；下一次保存也不应把损坏内容当成空 spec。
        assert yaml_path.read_text(encoding="utf-8") == raw


def test_ensure_session_repairs_missing_meta_and_preserves_entries(tmp_path):
    sessions = tmp_path / "sessions"
    sid = "sess-x"
    sdir = sessions / sid
    sdir.mkdir(parents=True)
    raw = json.dumps(_runtime_entry()) + "\n"
    (sdir / "entries.jsonl").write_text(raw, encoding="utf-8")

    ensure_session(sessions, sid)

    meta = json.loads((sdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["id"] == sid
    assert meta["active_cursor"] == ENTRY_1
    assert (sdir / "entries.jsonl").read_text(encoding="utf-8") == raw


def test_ensure_session_quarantines_corrupt_meta_without_touching_entries(tmp_path):
    sessions = tmp_path / "sessions"
    sid = "sess-corrupt"
    sdir = sessions / sid
    sdir.mkdir(parents=True)
    original = b'{"id": "sess-corrupt", "created_at": '
    raw = json.dumps(_runtime_entry()) + "\n"
    (sdir / "meta.json").write_bytes(original)
    (sdir / "entries.jsonl").write_text(raw, encoding="utf-8")

    ensure_session(sessions, sid)

    quarantined = list(sdir.glob("meta.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == original
    meta = json.loads((sdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["id"] == sid
    assert meta["active_cursor"] == ENTRY_1
    assert (sdir / "entries.jsonl").read_text(encoding="utf-8") == raw


def test_ensure_session_preserves_valid_runtime_meta(tmp_path):
    """runtime 写的合法 meta（纳秒时间 + 未知字段）不能被隔离/重写。"""
    sessions = tmp_path / "sessions"
    sid = "sess-valid"
    sdir = sessions / sid
    sdir.mkdir(parents=True)
    runtime_meta = {
        "id": sid,
        "name": "chat",
        "created_at": "2026-10-27T00:00:00.123456Z",
        "updated_at": "2026-10-27T00:00:01.987654Z",
        "model": "deepseek-chat",
        "active_cursor": ENTRY_1,
        "parent_session_path": None,
        "durability": "durable",
        "lifecycle": "active",
        "recall_policy": "disabled",
        "recall_revision": 7,
    }
    (sdir / "meta.json").write_text(json.dumps(runtime_meta), encoding="utf-8")
    (sdir / "entries.jsonl").write_text(
        json.dumps(_runtime_entry()) + "\n", encoding="utf-8"
    )

    ensure_session(sessions, sid)

    assert json.loads((sdir / "meta.json").read_text(encoding="utf-8")) == runtime_meta
    assert not list(sdir.glob("meta.json.corrupt-*"))


def test_repaired_session_meta_reconnects_last_entry_cursor(tmp_path):
    sessions = tmp_path / "sessions"
    sid = "sess-cursor"
    sdir = sessions / sid
    sdir.mkdir(parents=True)
    (sdir / "meta.json").write_text("", encoding="utf-8")
    (sdir / "entries.jsonl").write_text(
        json.dumps(_runtime_entry()) + "\n"
        + json.dumps(_runtime_entry(ENTRY_2, ENTRY_1, text="second", role="assistant"))
        + "\n"
        + '{"id": "truncated"',
        encoding="utf-8",
    )

    ensure_session(sessions, sid)

    meta = json.loads((sdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["active_cursor"] == ENTRY_2
    assert (sdir / "entries.jsonl").read_text(encoding="utf-8").endswith('{"id": "truncated"')


def test_unreachable_cursor_is_rejected_without_rewriting_meta(tmp_path):
    sessions = tmp_path / "sessions"
    sid = "sess-broken-cursor"
    sdir = sessions / sid
    sdir.mkdir(parents=True)
    meta = {
        "id": sid,
        "created_at": "2026-10-27T00:00:00Z",
        "updated_at": "2026-10-27T00:00:00Z",
        "model": None,
        "name": None,
        "active_cursor": ENTRY_2,
        "parent_session_path": None,
    }
    raw_meta = json.dumps(meta).encode("utf-8")
    raw_entries = (json.dumps(_runtime_entry()) + "\n").encode("utf-8")
    (sdir / "meta.json").write_bytes(raw_meta)
    (sdir / "entries.jsonl").write_bytes(raw_entries)

    with pytest.raises(RuntimeError, match="not reachable"):
        ensure_session(sessions, sid)

    assert (sdir / "meta.json").read_bytes() == raw_meta
    assert (sdir / "entries.jsonl").read_bytes() == raw_entries


def test_session_id_cannot_escape_sessions_dir(tmp_path):
    sessions = tmp_path / "sessions"
    with pytest.raises(ValueError):
        ensure_session(sessions, "../../escape")
    assert not (tmp_path / "escape").exists()


def test_history_read_ignores_only_unterminated_tail_and_rejects_interior_corruption(tmp_path):
    sessions = tmp_path / "sessions"
    sid = "sess-history"
    sdir = sessions / sid
    sdir.mkdir(parents=True)
    valid = json.dumps(_runtime_entry(text="hello")) + "\n"
    tail = '{"id": "half-written"'
    (sdir / "entries.jsonl").write_bytes(
        valid.encode("utf-8") + tail.encode("utf-8")
    )

    messages = read_session_history(sessions, sid)
    assert messages == [
        {"role": "user", "content": "hello", "timestamp": 1793059200000}
    ]

    (sdir / "entries.jsonl").write_bytes(
        valid.encode("utf-8")
        + b'{"id": "bad", "payload":\n'
        + b"\xff\xfe\n"
        + (json.dumps(_runtime_entry(ENTRY_2, ENTRY_1)) + "\n").encode("utf-8")
    )
    with pytest.raises(RuntimeError):
        read_session_history(sessions, sid)


def test_session_reader_does_not_split_unicode_line_separators(tmp_path):
    sessions = tmp_path / "sessions"
    sid = "sess-unicode"
    sdir = sessions / sid
    sdir.mkdir(parents=True)
    text = "第一行\u2028第二行\u2029第三行"
    raw = json.dumps(_runtime_entry(text=text), ensure_ascii=False) + "\n"
    (sdir / "entries.jsonl").write_text(raw, encoding="utf-8")

    ensure_session(sessions, sid)
    assert read_session_history(sessions, sid) == [
        {"role": "user", "content": text, "timestamp": 1793059200000}
    ]


def test_session_reader_tolerates_torn_multibyte_tail(tmp_path):
    sessions = tmp_path / "sessions"
    sid = "sess-torn-utf8"
    sdir = sessions / sid
    sdir.mkdir(parents=True)
    complete = json.dumps(_runtime_entry(text="完整"), ensure_ascii=False) + "\n"
    # 模拟进程在写 JSON 字符串时崩掉，截断在“你”的 UTF-8 字节中间。
    torn = '{"id":"0192f0aa-0000-7000-8000-000000000099","payload":{"text":"'.encode()
    torn += "你".encode()[:2]
    (sdir / "entries.jsonl").write_bytes(complete.encode("utf-8") + torn)

    ensure_session(sessions, sid)
    meta = json.loads((sdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["active_cursor"] == ENTRY_1
    assert read_session_history(sessions, sid) == [
        {"role": "user", "content": "完整", "timestamp": 1793059200000}
    ]
    assert (sdir / "entries.jsonl").read_bytes().endswith(torn)


def test_corrupt_settings_are_quarantined_before_next_save(cfg):
    save_settings(cfg, {"SENZA_STUDIO_MODEL": "first", "SENZA_STUDIO_API_KEY": "secret"})
    path = settings_path(cfg)
    original = b"not-json-original-bytes"
    path.write_bytes(original)

    with pytest.raises(OSError, match="已损坏"):
        save_settings(cfg, {"SENZA_STUDIO_MODEL": "second"})

    quarantined = list(path.parent.glob("settings.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == original
    assert not path.exists()
    save_settings(cfg, {"SENZA_STUDIO_MODEL": "second"})
    assert load_settings(cfg) == {"SENZA_STUDIO_MODEL": "second"}
    assert path.stat().st_mode & 0o777 == 0o600


def test_corrupt_project_is_hidden_from_list_and_reports_422(api_client, cfg):
    pid = api_client.post("/api/projects", json={"name": "p"}).json()["id"]
    state = _get_or_load_project(cfg, pid)
    (state["project"].path / ".studio" / "meta.json").write_text("", encoding="utf-8")
    _reset_state()

    assert api_client.get("/api/projects").json() == []
    r = api_client.get(f"/api/projects/{pid}")
    assert r.status_code == 422
    assert "损坏" in r.json()["detail"]


def test_update_spec_save_failure_keeps_memory_and_disk(api_client, cfg, monkeypatch):
    pid = api_client.post("/api/projects", json={"name": "p"}).json()["id"]
    state = _get_or_load_project(cfg, pid)
    old = state["spec"].get_current_spec()

    def boom(self, spec):
        raise OSError("disk full")

    monkeypatch.setattr(Project, "save_spec", boom)
    r = api_client.put(f"/api/projects/{pid}/spec", json={"spec": _valid_spec().get_current_spec()})
    assert r.status_code == 500
    assert r.json()["saved"] is False
    assert state["spec"].get_current_spec() == old
    assert api_client.get(f"/api/projects/{pid}/spec").json() == old


def test_update_spec_reports_saved_but_not_applied(api_client, cfg, monkeypatch):
    pid = api_client.post("/api/projects", json={"name": "p"}).json()["id"]
    state = _get_or_load_project(cfg, pid)
    state["agent"]._session_id = "sess-x"

    def fail_rebuild(self):
        raise RuntimeError("provider down")

    monkeypatch.setattr(type(state["agent"]), "rebuild", fail_rebuild)
    r = api_client.put(
        f"/api/projects/{pid}/spec",
        json={"spec": _valid_spec().get_current_spec()},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is True
    assert body["applied"] is False
    assert "已保存" in body["warning"]
    assert api_client.get(f"/api/projects/{pid}/spec").json() == _valid_spec().get_current_spec()


def test_update_spec_rejected_while_prompt_running(api_client, cfg):
    pid = api_client.post("/api/projects", json={"name": "p"}).json()["id"]
    state = _get_or_load_project(cfg, pid)
    state["prompt_run"] = {"run_id": "r", "status": "running"}
    r = api_client.put(
        f"/api/projects/{pid}/spec",
        json={"spec": _valid_spec().get_current_spec()},
    )
    assert r.status_code == 409
    assert api_client.get(f"/api/projects/{pid}/spec").json() == {"stages": []}


def test_settings_do_not_replace_harness_while_prompt_running(
    api_client, cfg, monkeypatch
):
    pid = api_client.post("/api/projects", json={"name": "p"}).json()["id"]
    state = _get_or_load_project(cfg, pid)
    state["agent"]._session_id = "sess-x"
    state["prompt_run"] = {"run_id": "r", "status": "running"}
    calls: list[int] = []
    monkeypatch.delenv("SENZA_STUDIO_MODEL", raising=False)
    # 全量测试里前一个 create_app 可能快照过某个测试临时 export 的模型
    # 环境变量；本测试需要确定性的“模型确实变了”。
    monkeypatch.setattr(settings_mod, "_env_overrides", frozenset())
    cfg.model = "test-model"
    monkeypatch.setattr(state["agent"], "rebuild", lambda: calls.append(1))

    r = api_client.put(
        "/api/settings",
        json={"values": {"SENZA_STUDIO_MODEL": "next-model"}},
    )
    assert r.status_code == 200
    assert calls == []
    assert state["harness_rebuild_pending"] is True
    assert any("结束后应用" in warning for warning in r.json()["warnings"])


def test_upload_does_not_replace_harness_while_prompt_running(
    api_client, cfg, monkeypatch
):
    pid = api_client.post("/api/projects", json={"name": "p"}).json()["id"]
    state = _get_or_load_project(cfg, pid)
    state["agent"]._session_id = "sess-x"
    state["prompt_run"] = {"run_id": "r", "status": "running"}
    calls: list[int] = []
    monkeypatch.setattr(state["agent"], "rebuild", lambda: calls.append(1))

    r = api_client.post(
        f"/api/projects/{pid}/documents",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 200
    assert calls == []
    assert r.json()["applied"] is False
    assert state["harness_rebuild_pending"] is True
