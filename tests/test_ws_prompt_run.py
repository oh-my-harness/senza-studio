"""prompt 执行生命周期测试——run_prompt_streaming 的终态记录与推送。

覆盖不变量:每个 PROMPT received 最终必须恰好对应一条终态
(completed / failed / cancelled),且终态归属由 Harness 执行结果决定,
与 WebSocket 生命周期无关。

直接驱动 run_prompt_streaming(不经过 uvicorn),用假 WebSocket +
假 agent 记录发送的消息,验证 state["prompt_run"] 的终态与
prompt_terminal 推送。
"""
import asyncio
import threading
import time

import pytest

from studio_backend.ws import run_prompt_streaming


class FakeWebSocket:
    """记录 send_json 调用;可选模拟死连接(发送抛异常)。"""

    def __init__(self, dead: bool = False):
        self.sent: list[dict] = []
        self.dead = dead

    async def send_json(self, obj):
        if self.dead:
            raise RuntimeError("connection closed")
        self.sent.append(obj)


class FakeAgent:
    """可控的假 agent:线程里跑 prompt,按脚本产生 harness 事件。"""

    def __init__(self, script: list[dict] | None = None, raise_exc: Exception | None = None,
                 abort_after: float | None = None):
        self._script = script
        self._raise = raise_exc
        self._abort_after = abort_after
        self._harness = self
        self.abort_called = False

    def events(self, timeout_ms=5000, max_consecutive_timeouts=999):
        for ev in self._script:
            yield ev

    def prompt(self, text, timeout_ms=30000):
        # 模拟真实 prompt_and_collect:阻塞到脚本放完;abort 场景下提前返回。
        if self._abort_after is not None:
            deadline = time.time() + self._abort_after
            while time.time() < deadline:
                time.sleep(0.02)
                if self.abort_called:
                    return [{"type": "aborted"}]
            return list(self._script)
        if self._raise:
            raise self._raise
        return list(self._script)

    def abort(self):
        self.abort_called = True


class FakeProject:
    def save_spec(self, spec):
        pass


def make_state():
    return {"spec": {"stages": []}, "prompt_run": None, "ws_socket": None}


def drain_async(coro):
    """在独立线程的事件循环里跑协程(prompt 线程是真实线程)。"""
    result = {}

    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result["task"] = loop.create_task(coro)
        try:
            loop.run_until_complete(result["task"])
        except Exception as exc:  # noqa: BLE001
            result["exc"] = exc

    import threading
    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return t, result


def terminal_sent(ws) -> dict | None:
    terms = [m for m in ws.sent if m.get("type") == "prompt_terminal"]
    return terms[-1] if terms else None


# ── 正常完成 ─────────────────────────────────────────────


def test_normal_completion_records_completed():
    """agent_end 到达 → drain 转发后 break → 记录 completed + prompt_terminal。"""
    ws = FakeWebSocket()
    script = [
        {"type": "phase_change", "from": "idle", "to": "turning"},
        {"type": "turn_start", "index": 0},
        {"type": "message_start", "message_id": "m1"},
        {"type": "text_delta", "text": "hi"},
        {"type": "message_end", "message_id": "m1", "text": "hi"},
        {"type": "turn_end", "index": 0, "message_text": "hi"},
        {"type": "agent_end", "new_messages_count": 1},
        {"type": "settled"},
    ]
    agent = FakeAgent(script=script)
    state = make_state()
    state["ws_socket"] = ws
    state["prompt_run"] = {"run_id": "r1", "prompt": "hi", "status": "running",
                           "error": None, "started_at": time.time(), "ended_at": None}

    async def run_all():
        await run_prompt_streaming(ws, agent, FakeProject(), "hi", state, "r1")

    t, result = drain_async(run_all())
    t.join(timeout=10)
    assert not result.get("task", None) or result["task"].done()

    record = state["prompt_run"]
    assert record["run_id"] == "r1"
    assert record["status"] == "completed"
    term = terminal_sent(ws)
    assert term is not None
    assert term["outcome"] == "completed"
    assert term["run_id"] == "r1"


# ── 执行失败 ─────────────────────────────────────────────


def test_execution_failure_records_failed():
    """agent.prompt 抛异常 → failed,error 消息进入记录与推送。"""
    ws = FakeWebSocket()
    agent = FakeAgent(raise_exc=RuntimeError("boom: provider down"))
    state = make_state()
    state["ws_socket"] = ws
    state["prompt_run"] = {"run_id": "r2", "prompt": "x", "status": "running",
                           "error": None, "started_at": time.time(), "ended_at": None}

    async def run_all():
        await run_prompt_streaming(ws, agent, FakeProject(), "hi", state, "r2")

    t, _ = drain_async(run_all())
    t.join(timeout=10)

    record = state["prompt_run"]
    assert record["status"] == "failed"
    assert "boom" in record["error"]
    term = terminal_sent(ws)
    assert term["outcome"] == "failed"
    assert "boom" in term["error"]


# ── 显式取消 ─────────────────────────────────────────────


def test_explicit_abort_records_cancelled():
    """abort() → prompt_and_collect 以 aborted 事件结束 → cancelled。"""
    ws = FakeWebSocket()
    # 脚本:正常 turn 开始后被 abort(脚本尾部 aborted,WS 中断事件也是它)
    script = [
        {"type": "phase_change", "from": "idle", "to": "turning"},
        {"type": "turn_start", "index": 0},
        {"type": "message_start", "message_id": "m1"},
        {"type": "aborted"},
    ]
    agent = FakeAgent(script=script)
    state = make_state()
    state["ws_socket"] = ws
    state["prompt_run"] = {"run_id": "r3", "prompt": "hi", "status": "running",
                           "error": None, "started_at": time.time(), "ended_at": None}

    async def run_all():
        await run_prompt_streaming(ws, agent, FakeProject(), "hi", state, "r3")

    t, _ = drain_async(run_all())
    t.join(timeout=10)

    assert state["prompt_run"]["status"] == "cancelled"
    term = terminal_sent(ws)
    assert term["outcome"] == "cancelled"


# ── 断连后执行仍完成 ─────────────────────────────────────


def test_disconnect_midrun_run_completes_later_record_true_outcome():
    """socket 断开(send 抛异常)→ drain 退出,但线程跑完 → 终态仍记录为
    completed,并把 prompt_terminal 推给 state["ws_socket"](新 socket)。"""
    dead_ws = FakeWebSocket(dead=True)
    script = [
        {"type": "phase_change", "from": "idle", "to": "turning"},
        {"type": "turn_start", "index": 0},
        {"type": "message_start", "message_id": "m1"},
        {"type": "text_delta", "text": "ok"},
        {"type": "message_end", "message_id": "m1", "text": "ok"},
        {"type": "turn_end", "index": 0, "message_text": "ok"},
        {"type": "agent_end", "new_messages_count": 1},
        {"type": "settled"},
    ]
    # 线程里 agent.prompt 会在第一个事件后延迟返回——用小延迟模拟"执行比
    # socket 活得久"
    agent = FakeAgent(script=script)

    state = make_state()
    state["ws_socket"] = dead_ws  # FM1:原 socket 已死
    state["prompt_run"] = {"run_id": "r4", "prompt": "hi", "status": "running",
                           "error": None, "started_at": time.time(), "ended_at": None}
    new_ws = FakeWebSocket()
    state["ws_socket"] = new_ws  # 重连后的新 socket

    async def run_all():
        await run_prompt_streaming(dead_ws, agent, FakeProject(), "hi", state, "r4")

    t, _ = drain_async(run_all())
    t.join(timeout=10)

    record = state["prompt_run"]
    assert record["status"] == "completed"
    # 终态推送投递到了新 socket(跨 run/跨 socket 投递)
    term = terminal_sent(new_ws)
    assert term is not None
    assert term["outcome"] == "completed"
    assert term["run_id"] == "r4"


# ── 重连对账(连接时推送 prompt_state)------------------------------


def test_reconnect_receives_prompt_state():
    """app.project_ws 连接时推送 prompt_run 记录——用 app 级测试覆盖,见
    test_reconnect_receives_prompt_state_after_completion(TestClient)。"""


# ── 旧 run 迟于新 run 开始才完成 -------------------------------


def test_stale_run_record_guard():
    """run A 未完成时 run B 开始 → A 的 drain finally 不得覆盖 B 的记录;
    A 的 prompt_terminal 仍然跨 run 投递到当前 socket。"""
    ws = FakeWebSocket()
    script = [
        {"type": "turn_start", "index": 0},
        {"type": "message_start", "message_id": "mA"},
        # 之后脚本结束 → 渠道耗尽 → StopIteration → finally
    ]
    agent = FakeAgent(script=script)
    state = make_state()
    # B 已经开始:记录被 B 占用
    state["ws_socket"] = ws
    state["prompt_run"] = {"run_id": "rB", "prompt": "b", "status": "running",
                           "error": None, "started_at": time.time(), "ended_at": None}

    async def run_a():
        await run_prompt_streaming(ws, agent, FakeProject(), "A", state, "rA")

    t, _ = drain_async(run_a())
    t.join(timeout=10)

    # 记录仍是 B(A 被 run_id 守卫拒绝)
    assert state["prompt_run"]["run_id"] == "rB"
    # 但 A 的终态推送照样到达当前 socket(前端按 run_id 归档到 A 的行)
    term = terminal_sent(ws)
    assert term is not None
    assert term["run_id"] == "rA"


# ── 取消事件可见性:aborted 属于 _TERMINAL_TYPES ------------------


def test_abort_event_forwarded_and_breaks():
    """aborted 事件转发给 socket 且触发 break(终态之一)。"""
    ws = FakeWebSocket()
    script = [
        {"type": "phase_change", "from": "idle", "to": "turning"},
        {"type": "aborted"},
    ]
    agent = FakeAgent(script=script)
    state = make_state()
    state["ws_socket"] = ws
    state["prompt_run"] = {"run_id": "r5", "prompt": "hi", "status": "running",
                           "error": None, "started_at": time.time(), "ended_at": None}

    async def run_all():
        await run_prompt_streaming(ws, agent, FakeProject(), "hi", state, "r5")

    t, _ = drain_async(run_all())
    t.join(timeout=10)

    types = [m.get("type") for m in ws.sent]
    assert "aborted" in types
    assert state["prompt_run"]["status"] == "cancelled"
    term = terminal_sent(ws)
    assert term["outcome"] == "cancelled"


# ── run_id 守卫:陈旧 drain 不得覆盖新 run ------------------------


def test_stale_drain_does_not_overwrite_newer_run_record():
    """drain 的 run_id 与 state["prompt_run"]["run_id"] 不一致 → 不回写。"""
    ws = FakeWebSocket(dead=True)
    agent = FakeAgent(script=[])  # 立即耗尽 → finally
    state = make_state()
    state["ws_socket"] = ws
    state["prompt_run"] = {"run_id": "rB", "prompt": "B", "status": "running",
                           "error": None, "started_at": time.time(), "ended_at": None}

    async def run_old():
        await run_prompt_streaming(ws, agent, FakeProject(), "A", state, "rA-old")

    t, _ = drain_async(run_old())
    t.join(timeout=10)

    # 记录仍是 B 的
    assert state["prompt_run"]["run_id"] == "rB"
    assert state["prompt_run"]["status"] == "running"


# ── 跨 run 投递:旧 run 完成于新 run 开始之后 ----------------------------


def test_old_run_terminal_pushed_to_current_socket():
    """A 断连后重连,B 启动;A 的 drain finally 把终态推给当前 socket(S2)。
    前端按 run_id 归档:A 的终态行照样追加到共享控制台,不影响 B 的计时。"""
    new_ws = FakeWebSocket()
    dead_ws = FakeWebSocket(dead=True)
    script = [
        {"type": "turn_start", "index": 0},
        {"type": "message_start", "message_id": "mA"},
        {"type": "message_end", "message_id": "mA", "text": "A done"},
        {"type": "turn_end", "index": 0, "message_text": "A done"},
        {"type": "agent_end", "new_messages_count": 1},
        {"type": "settled"},
    ]
    agent = FakeAgent(script=script)
    state = make_state()
    # A 在死 socket 上启动;重连后 B 已把当前 socket 换成 new_ws
    state["ws_socket"] = new_ws
    state["prompt_run"] = {"run_id": "rB", "prompt": "B", "status": "running",
                           "error": None, "started_at": time.time(), "ended_at": None}

    async def run_a():
        await run_prompt_streaming(dead_ws, agent, FakeProject(), "A", state, "rA")

    t, _ = drain_async(run_a())
    t.join(timeout=10)

    # A 的终态推给了 B 的 socket(跨 run 投递),消息里带 A 的 run_id
    term = terminal_sent(new_ws)
    assert term is not None
    assert term["run_id"] == "rA"
    # 记录未被 A 覆盖(run_id 守卫):仍是 B
    assert state["prompt_run"]["run_id"] == "rB"
    assert state["prompt_run"]["status"] == "running"


# ── 重连对账:连接时收到 prompt_state ---------------------------------


class LifecycleWebSocket:
    """直接驱动 project_ws：进入 receive_json 后等待测试触发断连。"""

    def __init__(self, token):
        self.headers = {"authorization": f"Bearer {token}"}
        self.cookies = {}
        self.receiving = asyncio.Event()
        self.disconnect = asyncio.Event()

    async def accept(self):
        pass

    async def close(self, code):
        pass

    async def send_json(self, obj):
        pass

    async def receive_json(self):
        from starlette.websockets import WebSocketDisconnect

        self.receiving.set()
        await self.disconnect.wait()
        raise WebSocketDisconnect()


def _project_ws_endpoint(monkeypatch, tmp_path):
    from studio_backend import app as app_module
    from studio_backend.app import create_app
    from studio_backend.config import StudioConfig

    token = "a" * 40
    state = {
        "agent": type("Agent", (), {"_harness": object()})(),
        "project": type("Project", (), {"meta": {}})(),
        "spec": {"stages": []},
        "prompt_run": None,
        "ws_socket": None,
    }
    monkeypatch.setattr(app_module, "_get_or_load_project", lambda cfg, pid: state)
    app = create_app(
        StudioConfig(
            home_dir=str(tmp_path / ".senza-studio"),
            model="test-model",
            api_key="test-key",
            api_base="",
            api_token=token,
        )
    )
    endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == "/ws/projects/{project_id}"
    )
    return endpoint, state, token


@pytest.mark.asyncio
async def test_disconnect_clears_owned_ws_socket(monkeypatch, tmp_path):
    """单个 socket 断开后不得留在 project state 里成为假活连接。"""
    endpoint, state, token = _project_ws_endpoint(monkeypatch, tmp_path)
    websocket = LifecycleWebSocket(token)
    task = asyncio.create_task(endpoint(websocket, "project"))
    await websocket.receiving.wait()
    assert state["ws_socket"] is websocket

    websocket.disconnect.set()
    await task
    assert state["ws_socket"] is None


@pytest.mark.asyncio
async def test_late_disconnect_does_not_clear_replacement_ws_socket(
    monkeypatch, tmp_path
):
    """A 的 cleanup 晚于 B 注册时只能释放 A，不能清掉当前的 B。"""
    endpoint, state, token = _project_ws_endpoint(monkeypatch, tmp_path)
    socket_a = LifecycleWebSocket(token)
    socket_b = LifecycleWebSocket(token)

    task_a = asyncio.create_task(endpoint(socket_a, "project"))
    await socket_a.receiving.wait()
    assert state["ws_socket"] is socket_a

    task_b = asyncio.create_task(endpoint(socket_b, "project"))
    await socket_b.receiving.wait()
    assert state["ws_socket"] is socket_b

    socket_a.disconnect.set()
    await task_a
    assert state["ws_socket"] is socket_b

    socket_b.disconnect.set()
    await task_b
    assert state["ws_socket"] is None




def test_reconnect_receives_prompt_state_after_completion(tmp_path):
    """重连后新连接收到最近一次 run 的终态记录(app.project_ws 连接即推送)。"""
    from fastapi.testclient import TestClient
    from studio_backend.app import create_app, _reset_state, _get_or_load_project
    from studio_backend.config import StudioConfig

    _reset_state()
    try:
        config = StudioConfig(home_dir=str(tmp_path / ".senza-studio"),
                              model="test-model", api_key="test-key", api_base="",
                              api_token="a" * 40)
        app = create_app(config)
        with TestClient(
            app,
            headers={"Origin": "http://localhost:5173"},
        ) as client:
            auth_headers = {"Authorization": "Bearer " + "a" * 40}
            r = client.post(
                "/api/projects",
                json={"name": "zzz-prompt-state-probe"},
                headers=auth_headers,
            )
            pid = r.json()["id"]
            # 放一条已完成的 run 记录(模拟断连后由线程分类完成)
            st = _get_or_load_project(config, pid)
            st["prompt_run"] = {"run_id": "r-done", "prompt": "hi",
                                "status": "completed", "error": None,
                                "started_at": 1.0, "ended_at": 2.0}
            with client.websocket_connect(
                f"/ws/projects/{pid}",
                subprotocols=["senza-studio-bearer-" + "a" * 40],
            ) as ws:
                msg = ws.receive_json()
                assert msg["type"] == "prompt_state"
                assert msg["run"]["run_id"] == "r-done"
                assert msg["run"]["status"] == "completed"
    finally:
        _reset_state()


# ── 真实压缩失败路径:compaction_end{error} + 线程 raise ------------------


def test_compaction_failure_full_observability():
    """真实 CompactionError 形状:线上出现 compaction_start →
    compaction_end{error:"no valid cut boundary..."} → prompt_and_collect 抛
    CompactionError。必须:compaction_end 原样转发(带 error 字段)、记录
    failed、prompt_terminal 推送 error 文本。"""
    ws = FakeWebSocket()
    script = [
        {"type": "phase_change", "from": "idle", "to": "turning"},
        {"type": "turn_start", "index": 0},
        {"type": "compaction_start"},
        {"type": "compaction_end", "stats": None,
         "error": "no valid cut boundary found in compaction path"},
    ]
    agent = FakeAgent(script=script,
                      raise_exc=RuntimeError("no valid cut boundary found in compaction path"))
    state = make_state()
    state["ws_socket"] = ws
    state["prompt_run"] = {"run_id": "rC", "prompt": "1+1=?", "status": "running",
                           "error": None, "started_at": 1.0, "ended_at": None}

    async def run_all():
        await run_prompt_streaming(ws, agent, None, "1+1=?", state, "rC")

    t, _ = drain_async(run_all())
    t.join(timeout=10)

    # 线程 raise → failed(与真实 AgentHarness.prompt() 压缩失败路径一致:
    # prompt_and_collect raise,而不是返回 aborted)
    run = state["prompt_run"]
    assert run["status"] == "failed"
    assert "no valid cut boundary" in run["error"]

    types = [m.get("type") for m in ws.sent]
    # compaction_end 原样转发(带 error 字段),prompt_terminal 推送 outcome=failed
    ce = [m for m in ws.sent if m.get("type") == "compaction_end"]
    assert ce and ce[-1]["error"] == "no valid cut boundary found in compaction path"
    term = terminal_sent(ws)
    assert term is not None
    assert term["outcome"] == "failed"
    assert "no valid cut boundary" in term["error"]
