"""Studio 和导出 Agent 跑同一个 spec，行为必须一致（Phase 7 切片四）。

这是整个 Phase 7 的验收标准。放在 senza-studio 的测试里而不是 runtime 包里，
因为只有这边能同时拿到两侧：Studio 的 app 和 runtime 的 serve app。

两边都用 TestClient 在进程内跑，不起真的服务器——真服务器的版本我手动验证过
一次（事件轨迹逐条相同），但那种测试太重、太慢，不适合每次提交都跑。这里比的
是同一批可观测事件：step 顺序、route_key、输出文本、终态。

用 checker + 能力组件的 spec：完全不需要 LLM（所以不受供应商故障影响），但覆盖
了预处理器展开、审批暂停、路由这几条最容易两边跑偏的路径。

**"一致"指的是行为，不是界面。** 导出的是做好的 agent，不是做它用的编辑器，
所以两边的 HTTP 接口刻意长得不一样：Studio 那边是 spec 编辑器的接口，这边只有
产品契约。下面 test_export_does_not_expose_the_editor 把这条钉死。
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
    # 顶层 ui 块：导出 Agent（和它的预览 Game view）顶上的文案
    "ui": {
        "title": "退款审批",
        "description": "确认之后自动退款",
        "inputs": {"reason": {"label": "退款理由", "multiline": False}},
    },
    "stages": [
        {
            "name": "gate",
            "component": "approval_flow",
            "params": {"title": "请确认这笔退款"},
            "next_on_approve": "refunded",
            "next_on_reject": "rejected",
        },
        {
            "name": "refunded",
            "type": "terminal",
            "message": "已退款",
            "ui": {"display": "chat"},
        },
        {
            "name": "rejected",
            "type": "terminal",
            "message": "已驳回",
            # 作者标成不展示——产品界面就不该出现它
            "ui": {"display": "none"},
        },
    ]
}


def _trace(ws, decision: str, verbs: dict[str, str]) -> list:
    """跑一遍，记录可比较的事件轨迹。

    verbs 是两边各自的消息名（Studio 是编辑器的 play/submit_decision，导出
    Agent 是产品的 start/decision）——比的是事件流，不是消息名。
    """
    out: list = []
    ws.send_json({"type": verbs["start"], "inputs": {}})
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
        {"type": verbs["decide"], "step_id": "gate_review", "decision": decision}
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


STUDIO_VERBS = {"start": "play", "decide": "submit_decision"}
EXPORT_VERBS = {"start": "start", "decide": "decision"}

# Studio 侧的 API 现在要认证（e909d9d）；导出 Agent 的 runtime 没有这一层
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
        studio_trace = _trace(ws, decision, STUDIO_VERBS)
    with export.websocket_connect("/ws/run") as ws:
        export_trace = _trace(ws, decision, EXPORT_VERBS)

    assert studio_trace == export_trace, (
        f"两边行为不一致\nstudio: {studio_trace}\nexport: {export_trace}"
    )
    # 顺带确认这条轨迹确实是我们以为的那条，而不是两边同样地错
    assert ("started", "gate_review") in studio_trace  # 组件展开了
    assert ("paused",) in studio_trace  # 停下来等人工审批
    assert ("started", expected_terminal) in studio_trace
    assert ("done", "succeeded") == studio_trace[-1]
    _reset_state()


def test_export_serves_the_same_entry_inputs(tmp_path):
    """开始表单靠这个问用户要种子输入——和 Studio 的控制条问的必须是同一批。"""
    studio, pid, config = _studio_client(tmp_path)
    export, _ = _export_client(tmp_path, config, pid)
    assert (
        studio.get(f"/api/projects/{pid}/entry_inputs").json()["fields"]
        == [field["name"] for field in export.get("/api/agent").json()["inputs"]]
    )
    _reset_state()


def test_agent_contract_describes_display_not_structure(tmp_path):
    """/api/agent 回的是**怎么展示**，不是流程长什么样。

    这条是"导出的不该是编辑器"在接口层的具体含义：展示配置要全（包括能力
    组件展开出来的 step，它在编辑态 spec 里根本不存在），但 prompt、工具、
    连到哪个 step 这些一个字都不回。
    """
    studio, pid, config = _studio_client(tmp_path)
    export, _ = _export_client(tmp_path, config, pid)
    info = export.get("/api/agent").json()

    assert info["title"] == "退款审批"  # spec 里 ui.title 优先于项目名
    assert info["error"] is None
    steps = info["steps"]

    # 组件展开出来的审批 step——不展开的话界面上根本没有可点的选项
    assert [c["value"] for c in steps["gate_review"]["choices"]] == ["approve", "reject"]
    assert steps["gate_review"]["terminal"] is False
    # 终点 step 要标出来，界面据此把最后一张卡片渲染成"结果"
    assert steps["refunded"]["terminal"] is True
    # 作者标了 none 的 step，契约里如实回传，由界面决定不画
    assert steps["rejected"]["display"] == "none"

    # 结构信息不能漏出去
    for name, step in steps.items():
        assert set(step) == {"title", "display", "fields", "choices", "terminal"}, name
    assert "stages" not in info
    _reset_state()


def test_export_does_not_expose_the_editor(tmp_path):
    """导出 Agent 不提供任何编辑器接口。

    这是用户提的那条要求在测试里的样子：交付的是做好的 agent，不是做它用的
    工具。前端拿不到 spec，就画不出 DAG / Inspector——不是"画得出但我们不画"。
    """
    studio, pid, config = _studio_client(tmp_path)
    export, _ = _export_client(tmp_path, config, pid)

    for path in (
        "/api/projects",
        "/api/projects/default",
        "/api/projects/default/spec",
        "/api/projects/default/expanded_spec",
        "/api/projects/default/entry_inputs",
        "/api/projects/default/messages",
        "/api/mode",
    ):
        # 没带 webui 时这些是 404；带了 webui 的话 SPA 兜底会回 index.html。
        # 无论哪种，都不会是一份 spec——断言没有 JSON 形态的 spec 漏出去。
        resp = export.get(path)
        if resp.status_code == 200:
            assert "application/json" not in resp.headers.get("content-type", "")

    # Studio 那边这些照常可用——导出瘦身不能反过来把编辑器削掉
    assert studio.get(f"/api/projects/{pid}/spec").status_code == 200
    assert studio.get(f"/api/projects/{pid}/expanded_spec").status_code == 200
    _reset_state()


def test_debugger_verbs_are_not_accepted(tmp_path):
    """pause / resume / step 是调试器的动词，产品里没有。

    发过去应该被静默忽略（不崩、不改状态），而不是真的把流程停住——否则
    随便谁打开 devtools 就能把一个正在服务的 agent 卡住。
    """
    studio, pid, config = _studio_client(tmp_path)
    export, _ = _export_client(tmp_path, config, pid)
    with export.websocket_connect("/ws/run") as ws:
        for verb in ("pause", "resume", "step"):
            ws.send_json({"type": verb})
        # 忽略之后连接还活着，正常的一轮照跑不误
        trace = _trace(ws, "approve", EXPORT_VERBS)
    assert ("done", "succeeded") == trace[-1]
    _reset_state()


def test_exported_pipeline_round_trips(tmp_path):
    """导出的 pipeline.yaml 读回来要和原 spec 一致——中文、嵌套 params 都不能
    在 YAML 往返里走样。"""
    studio, pid, config = _studio_client(tmp_path)
    _, target = _export_client(tmp_path, config, pid)
    loaded = yaml.safe_load((target / "pipeline.yaml").read_text(encoding="utf-8"))
    assert loaded == SPEC
    _reset_state()


def test_studio_and_export_serve_the_same_agent_contract(tmp_path):
    """Game view 和导出 Agent 渲染的是同一个组件，喂给它的数据也必须是同一份。

    这一条是"看到的就是发出去的"在接口层的样子：两边的契约由同一个
    describe_agent 生成，所以应该逐字节相同。不相同的话，Studio 里预览出来的
    界面和用户真正看到的界面就是两回事——而那正是 Game view 存在的意义。
    """
    studio, pid, config = _studio_client(tmp_path)
    export, _ = _export_client(tmp_path, config, pid)

    from_studio = studio.get(f"/api/projects/{pid}/agent").json()
    from_export = export.get("/api/agent").json()
    assert from_studio == from_export

    # 顺带确认这份契约确实带着作者写的文案，而不是两边同样地回了默认值
    assert from_studio["title"] == "退款审批"
    assert from_studio["description"] == "确认之后自动退款"
    _reset_state()


def test_agent_ui_copy_overrides_the_derived_defaults(tmp_path):
    """没写 ui 的 spec 用推导出来的默认值（项目名当标题、变量名 humanize 成
    label）；写了就用作者写的。默认值只是让草稿阶段能看，不是能交付的文案。"""
    studio, pid, config = _studio_client(tmp_path)

    bare = {k: v for k, v in SPEC.items() if k != "ui"}
    studio.put(f"/api/projects/{pid}/spec", json={"spec": bare})
    info = studio.get(f"/api/projects/{pid}/agent").json()
    assert info["title"] == "一致性"  # 退回项目名
    assert info["description"] == ""

    studio.put(f"/api/projects/{pid}/spec", json={"spec": SPEC})
    info = studio.get(f"/api/projects/{pid}/agent").json()
    assert info["title"] == "退款审批"
    _reset_state()
