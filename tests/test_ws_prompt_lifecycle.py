"""Prompt / Play 执行生命周期回归。

这些测试刻意使用真实 threading.Thread + 真实 asyncio 循环，只在 LLM/WS
边界用可控替身；目标是证明：
- 事件循环上的等待不再用 Event.wait / Thread.join；
- 转发任务被取消时，独立 finalizer 仍能写出恰一次终态并保存 spec；
- 跨连接不抢占，旧线程未退出时不会启动新任务；
- 重连后的实时事件投递到当前 socket；
- Play 收尾等待线程时也不冻结事件循环。
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from studio_backend import app as app_module
from studio_backend import ws as ws_mod
from studio_backend.ws import (
    finalize_play,
    harness_is_busy,
    run_prompt_streaming,
    stop_active_prompt,
)


class FakeWebSocket:
    def __init__(self, block_terminal: asyncio.Event | None = None):
        self.sent: list[dict] = []
        self.block_terminal = block_terminal
        self.terminal_sent = asyncio.Event()

    async def send_json(self, obj):
        if obj.get("type") == "prompt_terminal" and self.block_terminal is not None:
            await self.block_terminal.wait()
        self.sent.append(obj)
        if obj.get("type") == "prompt_terminal":
            self.terminal_sent.set()


class FakeHarness:
    def __init__(self, event_iter):
        self._event_iter = event_iter

    def events(self, timeout_ms=5000, max_consecutive_timeouts=999):
        return iter(self._event_iter)


class FakeAgent:
    def __init__(self, events, *, prompt_gate: threading.Event | None = None):
        self._harness = FakeHarness(events)
        self.prompt_gate = prompt_gate
        self.abort_calls = 0
        self.prompt_calls = 0
        self.rebuild_calls = 0

    def prompt(self, text, timeout_ms=30000):
        self.prompt_calls += 1
        if self.prompt_gate is not None:
            self.prompt_gate.wait(5)
        return []

    def abort(self):
        self.abort_calls += 1

    def rebuild(self):
        self.rebuild_calls += 1


class FakeSpec:
    def get_current_spec(self):
        return {"stages": []}


class FakeProject:
    def __init__(self):
        self.saved = 0

    def save_spec(self, spec):
        self.saved += 1


def make_state(ws: FakeWebSocket, run_id: str = "r1"):
    return {
        "spec": FakeSpec(),
        "prompt_run": {
            "run_id": run_id,
            "prompt": "hi",
            "status": "running",
            "error": None,
            "started_at": time.time(),
            "ended_at": None,
            "owner": "ws-test",
        },
        "ws_socket": ws,
        "prompt_task": None,
        "prompt_finalizer": None,
        "prompt_thread": None,
    }


async def wait_for(predicate, timeout=2.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


async def measure_loop_gap(stop: asyncio.Event, interval=0.02):
    gaps: list[float] = []
    last = time.monotonic()
    while not stop.is_set():
        await asyncio.sleep(interval)
        now = time.monotonic()
        gaps.append(now - last)
        last = now
    return gaps


@pytest.mark.asyncio
async def test_cancel_forwarder_does_not_lose_finalizer():
    """转发任务被取消后，finalizer 仍写终态、保存 spec（L1/L2/F-B）。"""
    prompt_gate = threading.Event()
    agent = FakeAgent([{"type": "settled"}], prompt_gate=prompt_gate)
    project = FakeProject()
    ws = FakeWebSocket()
    state = make_state(ws)

    stop_probe = asyncio.Event()
    probe = asyncio.create_task(measure_loop_gap(stop_probe))
    task = asyncio.create_task(
        run_prompt_streaming(ws, agent, project, "hi", state, "r1")
    )
    state["prompt_task"] = task

    # 给转发任务时间跑到 finalizer 的 async wait，再取消它。
    assert await wait_for(lambda: state.get("prompt_finalizer") is not None)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    prompt_gate.set()
    assert await wait_for(lambda: ws.terminal_sent.is_set())
    stop_probe.set()
    gaps = await probe
    await asyncio.sleep(0)

    assert max(gaps) < 0.25, f"event loop stalled: {max(gaps):.3f}s"
    assert state["prompt_run"]["status"] == "completed"
    assert await wait_for(lambda: project.saved == 1)
    assert [m["type"] for m in ws.sent].count("prompt_terminal") == 1


@pytest.mark.asyncio
async def test_cancel_while_terminal_send_is_blocked_still_saves():
    """终态发送被卡住时 cancel 转发任务，不会跳过 save_spec（L2 窄窗口）。"""
    prompt_gate = threading.Event()
    agent = FakeAgent([{"type": "settled"}], prompt_gate=prompt_gate)
    project = FakeProject()
    send_gate = asyncio.Event()
    ws = FakeWebSocket(block_terminal=send_gate)
    state = make_state(ws)

    task = asyncio.create_task(
        run_prompt_streaming(ws, agent, project, "hi", state, "r1")
    )
    state["prompt_task"] = task
    prompt_gate.set()
    assert await wait_for(lambda: state.get("prompt_finalizer") is not None)
    await asyncio.sleep(0.05)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    send_gate.set()
    assert await wait_for(lambda: ws.terminal_sent.is_set())
    assert await wait_for(lambda: project.saved == 1)
    assert state["prompt_run"]["status"] == "completed"


@pytest.mark.asyncio
async def test_save_failure_is_reported_but_execution_terminal_stays_completed():
    class FailingProject(FakeProject):
        def save_spec(self, spec):
            raise OSError("disk full")

    agent = FakeAgent([{"type": "settled"}])
    ws = FakeWebSocket()
    state = make_state(ws)
    await run_prompt_streaming(ws, agent, FailingProject(), "hi", state, "r1")

    types = [m.get("type") for m in ws.sent]
    assert state["prompt_run"]["status"] == "completed"
    assert "spec_save_failed" in types
    spec_event = next(m for m in ws.sent if m.get("type") == "spec_updated")
    assert spec_event["saved"] is False


@pytest.mark.asyncio
async def test_stuck_thread_is_not_reported_completed_and_blocks_next_run():
    """线程在 abort+grace 后仍活着：终态必须是 failed，且下一次被拒绝。"""
    prompt_gate = threading.Event()
    agent = FakeAgent([], prompt_gate=prompt_gate)
    project = FakeProject()
    ws = FakeWebSocket()
    state = make_state(ws)

    await run_prompt_streaming(
        ws,
        agent,
        project,
        "hi",
        state,
        "r1",
        thread_timeout_s=0.1,
        stop_grace_s=0.05,
    )

    assert state["prompt_run"]["status"] == "failed"
    assert "still running" in (state["prompt_run"]["error"] or "")
    assert state.get("prompt_thread") is not None
    assert state["prompt_thread"].is_alive()

    err = await stop_active_prompt(state, agent, "ws-test", grace_s=0.05)
    assert err is not None
    assert "线程仍在运行" in err

    prompt_gate.set()
    assert await wait_for(lambda: not state["prompt_thread"].is_alive(), timeout=2)


@pytest.mark.asyncio
async def test_timeout_budget_is_not_postponed_by_endless_nonterminal_events():
    """事件一直吐非终态时，预算仍从启动计时，终态必须有界出现。"""
    prompt_gate = threading.Event()
    events_gate = threading.Event()

    class EndlessNonTerminal:
        def __iter__(self):
            return self

        def __next__(self):
            if events_gate.is_set():
                raise StopIteration
            return {"type": "text_delta", "text": "tick"}

    agent = FakeAgent([], prompt_gate=prompt_gate)
    agent._harness = FakeHarness(EndlessNonTerminal())
    ws = FakeWebSocket()
    state = make_state(ws)
    started = time.monotonic()

    task = asyncio.create_task(
        run_prompt_streaming(
            ws,
            agent,
            FakeProject(),
            "hi",
            state,
            "r1",
            thread_timeout_s=0.12,
            stop_grace_s=0.05,
        )
    )
    state["prompt_task"] = task
    assert await wait_for(lambda: ws.terminal_sent.is_set(), timeout=2.0)
    elapsed = time.monotonic() - started
    assert elapsed < 1.0
    assert state["prompt_run"]["status"] == "failed"
    assert "timed out" in (state["prompt_run"]["error"] or "")
    assert agent.abort_calls == 1

    events_gate.set()
    prompt_gate.set()
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_thread_exit_without_terminal_is_bounded_by_drain_not_full_budget():
    events_gate = threading.Event()

    class BlockedEvents:
        def __iter__(self):
            return self

        def __next__(self):
            assert events_gate.wait(5)
            raise StopIteration

    agent = FakeAgent([])
    agent._harness = FakeHarness(BlockedEvents())
    ws = FakeWebSocket()
    state = make_state(ws)
    started = time.monotonic()

    task = asyncio.create_task(
        run_prompt_streaming(
            ws,
            agent,
            FakeProject(),
            "hi",
            state,
            "r1",
            thread_timeout_s=5.0,
            stop_grace_s=0.05,
        )
    )
    state["prompt_task"] = task
    assert await wait_for(lambda: ws.terminal_sent.is_set(), timeout=2.0)
    assert time.monotonic() - started < 1.0
    assert state["prompt_run"]["status"] == "failed"
    assert "without a terminal" in (state["prompt_run"]["error"] or "")

    events_gate.set()
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_completed_run_not_misclassified_while_nonterminal_send_is_slow():
    """线程已退出，但终态还排在慢发送后面：deadline 必须等完整 grace。"""
    agent = FakeAgent([{"type": "text_delta"}, {"type": "settled"}])
    send_gate = asyncio.Event()

    class BlockingDeltaSocket(FakeWebSocket):
        async def send_json(self, obj):
            if obj.get("type") == "text_delta":
                await send_gate.wait()
            self.sent.append(obj)
            if obj.get("type") == "prompt_terminal":
                self.terminal_sent.set()

    ws = BlockingDeltaSocket()
    state = make_state(ws)

    task = asyncio.create_task(
        run_prompt_streaming(
            ws,
            agent,
            FakeProject(),
            "hi",
            state,
            "r1",
            thread_timeout_s=0.1,
            stop_grace_s=0.5,
        )
    )
    state["prompt_task"] = task

    # deadline 已过，线程早退，但转发仍卡在非终态发送；旧实现会在
    # 200ms 后把本轮判成 no-terminal。现在必须保持 running，等 grace。
    await asyncio.sleep(0.3)
    assert state["prompt_run"]["status"] == "running"
    send_gate.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert state["prompt_run"]["status"] == "completed"
    assert [m["type"] for m in ws.sent].count("prompt_terminal") == 1
    assert not ws.sent[-1].get("outcome") == "failed"


@pytest.mark.asyncio
async def test_sdk_timeout_sentinel_after_thread_exit_is_not_waited_forever():
    agent = FakeAgent([{"type": "timeout"}])
    ws = FakeWebSocket()
    state = make_state(ws)

    await asyncio.wait_for(
        run_prompt_streaming(ws, agent, FakeProject(), "hi", state, "r1"),
        timeout=2.0,
    )
    assert state["prompt_run"]["status"] == "failed"
    assert "without a terminal" in (state["prompt_run"]["error"] or "")
    assert "timeout" not in [
        m.get("type") for m in ws.sent if m.get("type") != "prompt_terminal"
    ]


@pytest.mark.asyncio
async def test_pending_harness_rebuild_waits_until_run_finishes():
    agent = FakeAgent([{"type": "settled"}])
    ws = FakeWebSocket()
    state = make_state(ws)
    state["harness_rebuild_pending"] = True

    await run_prompt_streaming(ws, agent, FakeProject(), "hi", state, "r1")

    assert agent.rebuild_calls == 1
    assert not state.get("harness_rebuild_pending")
    assert harness_is_busy(state) is False


@pytest.mark.asyncio
async def test_cross_connection_cannot_abort_or_preempt():
    blocker = asyncio.create_task(asyncio.sleep(10))
    agent = FakeAgent([])
    state = {
        "prompt_run": {"run_id": "r", "status": "running", "owner": "ws-A"},
        "prompt_task": blocker,
        "prompt_finalizer": None,
        "prompt_thread": None,
    }
    try:
        err = await stop_active_prompt(state, agent, "ws-B", grace_s=0.05)
        assert err is not None
        assert "另一个连接" in err
        assert agent.abort_calls == 0
    finally:
        blocker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await blocker


@pytest.mark.asyncio
async def test_reconnect_midrun_receives_later_events_and_terminal():
    prompt_gate = threading.Event()
    events_gate = threading.Event()

    class GatedEvents:
        def __init__(self):
            self.n = 0

        def __iter__(self):
            return self

        def __next__(self):
            self.n += 1
            if self.n == 1:
                return {"type": "turn_start", "index": 0}
            if self.n == 2:
                assert events_gate.wait(2)
                return {"type": "text_delta", "text": "hi"}
            if self.n == 3:
                return {"type": "settled"}
            raise StopIteration

    agent = FakeAgent([])
    agent._harness = FakeHarness(GatedEvents())
    # FakeAgent.prompt doesn't use prompt_gate here; use a cancellable no-op.
    project = FakeProject()
    old_ws = FakeWebSocket()
    new_ws = FakeWebSocket()
    state = make_state(old_ws)
    state["prompt_run"]["owner"] = "ws-test"

    task = asyncio.create_task(
        run_prompt_streaming(old_ws, agent, project, "hi", state, "r1")
    )
    state["prompt_task"] = task
    assert await wait_for(
        lambda: any(m.get("type") == "turn_start" for m in old_ws.sent)
    )

    # 模拟重连：旧 socket 槽被新连接替换。后续事件必须送到新 socket。
    state["ws_socket"] = new_ws
    events_gate.set()
    assert await wait_for(lambda: new_ws.terminal_sent.is_set())
    await task

    assert any(m.get("type") == "text_delta" for m in new_ws.sent)
    assert not any(m.get("type") == "text_delta" for m in old_ws.sent)
    assert state["prompt_run"]["status"] == "completed"


class QueuedWebSocket:
    """把 project_ws 真正跑起来：按队列投递消息，记录 send_json。"""

    def __init__(self, token):
        self.headers = {"authorization": f"Bearer {token}"}
        self.cookies = {}
        self.messages: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []
        self.receiving = asyncio.Event()

    async def accept(self):
        pass

    async def close(self, code):
        pass

    async def send_json(self, obj):
        self.sent.append(obj)

    async def receive_json(self):
        from starlette.websockets import WebSocketDisconnect

        self.receiving.set()
        item = await self.messages.get()
        if item is None:
            raise WebSocketDisconnect()
        return item


def _app_ws_endpoint(monkeypatch, tmp_path):
    from studio_backend import app as app_module
    from studio_backend.app import create_app
    from studio_backend.config import StudioConfig

    token = "a" * 40
    agent = FakeAgent([])
    agent._harness = FakeHarness([])
    project = FakeProject()
    project.meta = {}
    state = {
        "agent": agent,
        "project": project,
        "spec": FakeSpec(),
        "prompt_run": None,
        "ws_socket": None,
        "prompt_task": None,
        "prompt_finalizer": None,
        "prompt_thread": None,
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
    return endpoint, state, token, agent, project


@pytest.mark.asyncio
async def test_second_connection_prompt_is_rejected_without_aborting_owner(
    monkeypatch, tmp_path
):
    endpoint, state, token, agent, project = _app_ws_endpoint(monkeypatch, tmp_path)
    prompt_gate = threading.Event()
    agent.prompt_gate = prompt_gate

    ws_a = QueuedWebSocket(token)
    ws_b = QueuedWebSocket(token)
    task_a = asyncio.create_task(endpoint(ws_a, "project"))
    await ws_a.receiving.wait()
    ws_a.messages.put_nowait(
        {"type": "prompt", "text": "A", "run_id": "rA"}
    )
    assert await wait_for(lambda: state.get("prompt_task") is not None)

    task_b = asyncio.create_task(endpoint(ws_b, "project"))
    await ws_b.receiving.wait()
    ws_b.messages.put_nowait(
        {"type": "prompt", "text": "B", "run_id": "rB"}
    )
    assert await wait_for(
        lambda: any(
            m.get("type") == "error" and "另一个连接" in m.get("message", "")
            for m in ws_b.sent
        )
    )
    assert agent.abort_calls == 0
    assert state["prompt_run"]["run_id"] == "rA"

    prompt_gate.set()
    assert await wait_for(
        lambda: state["prompt_run"]["status"] in ("completed", "failed", "cancelled")
    )
    assert await wait_for(lambda: project.saved == 1)

    ws_a.messages.put_nowait(None)
    ws_b.messages.put_nowait(None)
    await asyncio.gather(task_a, task_b)


@pytest.mark.asyncio
async def test_play_task_and_owner_are_project_state_not_handler_local(
    monkeypatch, tmp_path
):
    endpoint, state, token, _agent, _project = _app_ws_endpoint(monkeypatch, tmp_path)
    finish = asyncio.Event()

    class FakePlaySession:
        def __init__(self):
            self.stopped = False

        def play(self, inputs=None, start_paused=False):
            pass

        def state(self):
            return "cancelled" if self.stopped else "running"

        def stop(self, reason):
            self.stopped = True
            finish.set()

    async def fake_stream(ws, play_session, project, state):
        try:
            await finish.wait()
        finally:
            finish.set()

    monkeypatch.setattr(
        app_module, "PlaySession", lambda cfg, project, spec: FakePlaySession()
    )
    monkeypatch.setattr(app_module, "run_play_streaming", fake_stream)

    ws_a = QueuedWebSocket(token)
    task_a = asyncio.create_task(endpoint(ws_a, "project"))
    await ws_a.receiving.wait()
    ws_a.messages.put_nowait({"type": "play"})
    assert await wait_for(lambda: state.get("play_task") is not None)

    ws_b = QueuedWebSocket(token)
    task_b = asyncio.create_task(endpoint(ws_b, "project"))
    await ws_b.receiving.wait()
    ws_b.messages.put_nowait({"type": "play"})
    ws_b.messages.put_nowait({"type": "stop"})
    assert await wait_for(
        lambda: len(
            [
                m
                for m in ws_b.sent
                if m.get("type") == "error" and "另一个连接" in m.get("message", "")
            ]
        )
        >= 2
    )
    assert state["play_owner"] and state["play_task"] is not None

    # A 断开只收掉 A 自己的 Play；B 之后可以重新开始。
    ws_a.messages.put_nowait(None)
    await task_a
    assert await wait_for(lambda: state.get("play_task") is None)

    finish.clear()
    ws_b.messages.put_nowait({"type": "play"})
    assert await wait_for(lambda: state.get("play_task") is not None)
    finish.set()
    assert await wait_for(lambda: state.get("play_task") is None)
    ws_b.messages.put_nowait(None)
    await task_b


@pytest.mark.asyncio
async def test_websocket_entrypoint_enforces_prompt_budget(monkeypatch, tmp_path):
    endpoint, state, token, agent, project = _app_ws_endpoint(monkeypatch, tmp_path)
    prompt_gate = threading.Event()
    agent.prompt_gate = prompt_gate
    monkeypatch.setattr(ws_mod, "PROMPT_THREAD_TIMEOUT_S", 0.12)
    monkeypatch.setattr(ws_mod, "PROMPT_STOP_GRACE_S", 0.05)

    ws = QueuedWebSocket(token)
    task = asyncio.create_task(endpoint(ws, "project"))
    await ws.receiving.wait()
    ws.messages.put_nowait({"type": "prompt", "text": "slow", "run_id": "rSlow"})
    assert await wait_for(
        lambda: (
            isinstance(state.get("prompt_run"), dict)
            and state["prompt_run"].get("status") == "failed"
            and "timed out" in (state["prompt_run"].get("error") or "")
        ),
        timeout=2.0,
    )
    assert any(
        m.get("type") == "prompt_terminal" and m.get("outcome") == "failed"
        for m in ws.sent
    )

    prompt_gate.set()
    ws.messages.put_nowait(None)
    await task
    assert await wait_for(lambda: project.saved == 1)


@pytest.mark.asyncio
async def test_reconnected_connection_can_abort_orphan_run(monkeypatch, tmp_path):
    endpoint, state, token, agent, project = _app_ws_endpoint(monkeypatch, tmp_path)
    prompt_gate = threading.Event()
    agent.prompt_gate = prompt_gate

    ws_a = QueuedWebSocket(token)
    task_a = asyncio.create_task(endpoint(ws_a, "project"))
    await ws_a.receiving.wait()
    ws_a.messages.put_nowait({"type": "prompt", "text": "A", "run_id": "rA"})
    assert await wait_for(lambda: state.get("prompt_task") is not None)
    owner = state["prompt_run"]["owner"]

    # A 断开：owner 不再在线，但 run 仍在跑。
    ws_a.messages.put_nowait(None)
    await task_a
    assert owner not in state["ws_connections"]

    ws_b = QueuedWebSocket(token)
    task_b = asyncio.create_task(endpoint(ws_b, "project"))
    await ws_b.receiving.wait()
    ws_b.messages.put_nowait({"type": "abort"})
    assert await wait_for(lambda: agent.abort_calls == 1)

    prompt_gate.set()
    assert await wait_for(
        lambda: state["prompt_run"]["status"] in ("completed", "failed", "cancelled")
    )
    ws_b.messages.put_nowait(None)
    await task_b
    assert await wait_for(lambda: project.saved == 1)


@pytest.mark.asyncio
async def test_switch_session_rejected_while_finalizer_pending(monkeypatch, tmp_path):
    endpoint, state, token, agent, _project = _app_ws_endpoint(monkeypatch, tmp_path)
    finalizer = asyncio.create_task(asyncio.sleep(10))
    state["prompt_finalizer"] = finalizer
    ws = QueuedWebSocket(token)
    task = asyncio.create_task(endpoint(ws, "project"))
    await ws.receiving.wait()
    ws.messages.put_nowait({"type": "switch_session", "session_id": "sess-2"})
    assert await wait_for(
        lambda: any(
            m.get("type") == "error" and "不能切换 session" in m.get("message", "")
            for m in ws.sent
        )
    )
    ws.messages.put_nowait(None)
    await task
    finalizer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await finalizer


@pytest.mark.asyncio
async def test_disconnect_does_not_cancel_running_prompt(monkeypatch, tmp_path):
    endpoint, state, token, agent, project = _app_ws_endpoint(monkeypatch, tmp_path)
    prompt_gate = threading.Event()
    agent.prompt_gate = prompt_gate

    ws = QueuedWebSocket(token)
    task = asyncio.create_task(endpoint(ws, "project"))
    await ws.receiving.wait()
    ws.messages.put_nowait({"type": "prompt", "text": "A", "run_id": "rA"})
    assert await wait_for(lambda: state.get("prompt_task") is not None)
    run_task = state["prompt_task"]

    # 断线：handler 退出，但 run 任务必须继续。
    ws.messages.put_nowait(None)
    await task
    assert state["ws_socket"] is None
    assert not run_task.done()

    prompt_gate.set()
    assert await wait_for(
        lambda: state["prompt_run"]["status"] in ("completed", "failed", "cancelled")
    )
    assert not run_task.cancelled()
    assert await wait_for(lambda: project.saved == 1)


@pytest.mark.asyncio
async def test_play_meta_save_is_off_loop_and_failure_is_visible():
    class SlowMetaProject(FakeProject):
        def __init__(self):
            super().__init__()
            self.meta = {"status": "playing"}

        def _save_meta(self):
            time.sleep(0.2)

    ws = FakeWebSocket()
    project = SlowMetaProject()
    stop_probe = asyncio.Event()
    probe = asyncio.create_task(measure_loop_gap(stop_probe))
    await finalize_play(ws, project)
    stop_probe.set()
    gaps = await probe

    assert max(gaps) < 0.1, f"play meta save stalled loop: {max(gaps):.3f}s"
    assert project.meta["status"] == "editing"

    class FailingMetaProject(SlowMetaProject):
        def _save_meta(self):
            raise OSError("disk full")

    failing = FailingMetaProject()
    failing_ws = FakeWebSocket()
    await finalize_play(failing_ws, failing)
    assert failing.meta["status"] == "playing"
    assert any(
        m.get("type") == "error" and "保存 Play" in m.get("message", "")
        for m in failing_ws.sent
    )


@pytest.mark.asyncio
async def test_play_finalizer_does_not_block_event_loop(monkeypatch):
    from senza_studio_runtime import stream as stream_mod

    monkeypatch.setattr(stream_mod, "PLAY_STOP_GRACE_S", 0.2)
    thread = threading.Thread(target=lambda: time.sleep(1.0), daemon=True)
    thread.start()

    class FakePlaySession:
        _thread = thread
        runtime_spec = None
        plugin_errors: list = []
        run_error = None

        def events(self, timeout_ms=250, max_consecutive_timeouts=20000):
            return iter([None])

        def start(self):
            pass

        def state(self):
            return "cancelled"

    finished = asyncio.Event()

    async def on_finished():
        finished.set()

    class Ws:
        async def send_json(self, obj):
            pass

    stop_probe = asyncio.Event()
    probe = asyncio.create_task(measure_loop_gap(stop_probe))
    await stream_mod.run_play_streaming(Ws(), FakePlaySession(), on_finished)
    stop_probe.set()
    gaps = await probe

    assert max(gaps) < 0.2, f"play finalizer stalled loop: {max(gaps):.3f}s"
    assert finished.is_set()
