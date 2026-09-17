"""Studio 和导出项目跑同一个 spec，行为必须一致（Phase 7 切片四）。

这是整个 Phase 7 的验收标准。放在 senza-studio 的测试里而不是 runtime 包里，
因为只有这边能同时拿到两侧：Studio 的 app 和 runtime 的 serve app。

两边都用 TestClient 在进程内跑，不起真的服务器——真服务器的版本我手动验证过
一次（事件轨迹逐条相同），但那种测试太重、太慢，不适合每次提交都跑。这里比的
是同一批可观测事件：step 顺序、route_key、输出文本、终态。

用 checker + 能力组件的 spec：完全不需要 LLM（所以不受供应商故障影响），但覆盖
了预处理器展开、审批暂停、路由这几条最容易两边跑偏的路径。
"""
from __future__ import annotations


import pytest
import yaml
from fastapi.testclient import TestClient

from senza_studio_runtime.serve import create_app as create_export_app
from studio_backend.app import _reset_state, create_app as create_studio_app
from studio_backend.config import StudioConfig
from studio_backend.export import export_project
from studio_backend.project import Project
from studio_backend.spec import Spec

SPEC = {
    "stages": [
        {
            "name": "gate",
            "component": "approval_flow",
            "params": {"title": "请确认这笔退款"},
            "next_on_approve": "refunded",
            "next_on_reject": "rejected",
        },
        {"name": "refunded", "type": "terminal", "message": "已退款"},
        {"name": "rejected", "type": "terminal", "message": "已驳回"},
    ]
}


def _trace(ws, decision: str) -> list:
    """跑一遍，记录可比较的事件轨迹。"""
    out: list = []
    ws.send_json({"type": "play", "inputs": {}})
    while True:
        ev = ws.receive_json()
        kind = ev.get("type")
        if kind == "step_started":
            out.append(("started", ev["step_id"]))
        elif kind == "step_finished":
            out.append(
                (
                    "finished",
                    ev["step_id"],
                    (ev.get("structured") or {}).get("route_key"),
                    ev.get("output"),
                )
            )
        elif kind == "paused":
            out.append(("paused",))
            break
        elif kind in ("error", "failed"):
            out.append((kind, str(ev)[:120]))
            return out

    ws.send_json(
        {"type": "submit_decision", "step_id": "gate_review", "decision": decision}
    )
    while True:
        ev = ws.receive_json()
        kind = ev.get("type")
        if kind == "step_started":
            out.append(("started", ev["step_id"]))
        elif kind == "step_finished":
            out.append(
                (
                    "finished",
                    ev["step_id"],
                    (ev.get("structured") or {}).get("route_key"),
                    ev.get("output"),
                )
            )
        elif kind == "workflow_done":
            out.append(("done", ev.get("state")))
            break
    return out


# Studio 侧的 API 现在要认证（e909d9d）；导出项目的 runtime 没有这一层
# ——它跑在用户自己机器上，前面也没有元 agent 那种会写文件的能力。
STUDIO_TOKEN = "studio-test-token-0123456789abcdef"


def _studio_client(tmp_path):
    _reset_state()
    config = StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test-model",
        api_key="k",
        api_base="",
        api_token=STUDIO_TOKEN,
    )
    client = TestClient(
        create_studio_app(config),
        headers={"Authorization": f"Bearer {STUDIO_TOKEN}"},
    )
    pid = client.post("/api/projects", json={"name": "一致性"}).json()["id"]
    client.put(f"/api/projects/{pid}/spec", json={"spec": SPEC})
    return client, pid, config


def _export_client(tmp_path, config, pid):
    """真的走一遍导出，再从导出目录起 serve——不是手搓一个目录。
    导出漏拷了什么、生成的 pipeline.yaml 有问题，这里都会暴露。"""
    project = Project.open(config, pid)
    target, _, _ = export_project(project, Spec(SPEC))
    return TestClient(create_export_app(target / "pipeline.yaml")), target


@pytest.mark.parametrize("decision,expected_terminal", [("approve", "refunded"), ("reject", "rejected")])
def test_studio_and_export_produce_identical_traces(tmp_path, decision, expected_terminal):
    studio, pid, config = _studio_client(tmp_path)
    export, _ = _export_client(tmp_path, config, pid)

    with studio.websocket_connect(f"/ws/projects/{pid}") as ws:
        studio_trace = _trace(ws, decision)
    with export.websocket_connect("/ws/projects/default") as ws:
        export_trace = _trace(ws, decision)

    assert studio_trace == export_trace, (
        f"两边行为不一致\nstudio: {studio_trace}\nexport: {export_trace}"
    )
    # 顺带确认这条轨迹确实是我们以为的那条，而不是两边同样地错
    assert ("started", "gate_review") in studio_trace  # 组件展开了
    assert ("paused",) in studio_trace  # 停下来等人工审批
    assert ("started", expected_terminal) in studio_trace
    assert ("done", "succeeded") == studio_trace[-1]
    _reset_state()


def test_export_serves_the_same_expanded_spec(tmp_path):
    """画布靠 expanded_spec 画组件 group，两边必须一模一样。"""
    studio, pid, config = _studio_client(tmp_path)
    export, _ = _export_client(tmp_path, config, pid)
    a = studio.get(f"/api/projects/{pid}/expanded_spec").json()
    b = export.get("/api/projects/default/expanded_spec").json()
    assert a == b
    _reset_state()


def test_export_serves_the_same_entry_inputs(tmp_path):
    """ControlBar 靠这个问用户要种子输入。"""
    studio, pid, config = _studio_client(tmp_path)
    export, _ = _export_client(tmp_path, config, pid)
    assert (
        studio.get(f"/api/projects/{pid}/entry_inputs").json()
        == export.get("/api/projects/default/entry_inputs").json()
    )
    _reset_state()


def test_exported_pipeline_round_trips(tmp_path):
    """导出的 pipeline.yaml 读回来要和原 spec 一致——中文、嵌套 params 都不能
    在 YAML 往返里走样。"""
    studio, pid, config = _studio_client(tmp_path)
    _, target = _export_client(tmp_path, config, pid)
    loaded = yaml.safe_load((target / "pipeline.yaml").read_text(encoding="utf-8"))
    assert loaded == SPEC
    _reset_state()


def test_export_mode_is_advertised(tmp_path):
    """前端靠 /api/mode 决定要不要渲染对话面板。Studio 那边没有这个路由，
    探测不到就当 studio——所以 Studio 侧不用为此改任何东西。"""
    studio, pid, config = _studio_client(tmp_path)
    export, _ = _export_client(tmp_path, config, pid)
    assert export.get("/api/mode").json()["mode"] == "export"
    assert studio.get("/api/mode").status_code == 404
    _reset_state()
