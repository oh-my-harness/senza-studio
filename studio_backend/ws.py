"""WebSocket 连接管理 + 事件转发。

将元 agent 的 streaming 事件转发给前端 WebSocket。
"""
from __future__ import annotations

import asyncio
import sys
import threading
import time

from fastapi import WebSocket

from .agent import StudioAgent
from senza_studio_runtime import stream as _runtime_stream

from .play import PlaySession
from .project import Project


# 事件类型标记一轮对话终止（SDK _TERMINAL_TYPES 的子集，适用于 agent harness）
_TERMINAL_TYPES = frozenset({"settled", "aborted", "error", "agent_end"})

# SDK 内部事件类型，不应转发给前端
_SKIP_TYPES = frozenset({"timeout"})

# 后台线程的安全上限。它不是“单次事件空闲超时”，而是整个执行的硬预算：
# 超时后只 abort 并等一个短 grace，仍不退出就明确记为 failed，绝不猜 completed。
# 断线本身不会触发它——断线只影响投递，不影响仍在正常推进的 run。
PROMPT_THREAD_TIMEOUT_S = 30 * 60.0

# 新 prompt 抢占旧 prompt（或用户 abort）时等待旧线程收尾的上限。
PROMPT_STOP_GRACE_S = 10.0

# 单条 WS 消息发送上限。慢客户端不能无限期拖住 finalizer；超时只丢这一条
# 实时事件，终态仍由 state 记录并在重连 prompt_state 中对账。
WS_SEND_TIMEOUT_S = 10.0

_WAIT_INTERVAL_S = 0.05


def project_lock(state: dict) -> asyncio.Lock:
    """每个项目一把 async 锁，串行化 meta/spec 等整文件提交。"""
    lock = state.get("project_lock")
    if lock is None:
        lock = asyncio.Lock()
        state["project_lock"] = lock
    return lock


def prompt_is_active(state: dict) -> bool:
    run = state.get("prompt_run")
    task = state.get("prompt_task")
    finalizer = state.get("prompt_finalizer")
    thread = state.get("prompt_thread")
    return (
        (isinstance(run, dict) and run.get("status") == "running")
        or (task is not None and not task.done())
        or (finalizer is not None and not finalizer.done())
        or (thread is not None and thread.is_alive())
    )


def play_is_active(state: dict) -> bool:
    task = state.get("play_task")
    if task is not None and not task.done():
        return True
    play_session = state.get("play_session")
    if play_session is None:
        return False
    try:
        return play_session.state() in ("running", "paused")
    except Exception:
        return False


def harness_is_busy(state: dict) -> bool:
    """Prompt/Play 正在使用共享 harness 时，任何入口都不得替换它。"""
    return prompt_is_active(state) or play_is_active(state)


def owner_is_live(state: dict, owner: str | None) -> bool:
    """owner 连接是否仍在线。

    没有登记表的老测试/旧 state 视为在线（保守拒绝跨连接抢占）；真实 WS
    handler 会维护 ws_connections，断线后 owner 不在集合里，重连才能接管
    一个已失去所有者的 run。
    """
    if owner is None:
        return False
    connections = state.get("ws_connections")
    if connections is None:
        return True
    return owner in connections


async def _send_live(state: dict, obj: dict) -> None:
    """向 state 里当前活跃的 socket 投递一条消息（尽力而为）。

    每一条事件都重新读取 state["ws_socket"]：连接在 run 中途重连后，后续
    实时事件要继续送到新连接，而不是死在创建任务时捕获的旧 socket 上。
    """
    target = state.get("ws_socket")
    if target is None:
        return
    try:
        await asyncio.wait_for(target.send_json(obj), timeout=WS_SEND_TIMEOUT_S)
    except asyncio.CancelledError:
        raise
    except Exception:
        pass


async def _wait_run_settled(
    done: threading.Event,
    events_finished: asyncio.Event,
    deadline: float,
    terminal_seen: dict | None = None,
) -> bool:
    """等线程退出且事件转发结束；deadline 是绝对 loop 时间。

    预算从 run 启动时开始，而不是从 events_finished 之后开始——否则事件
    迭代器一直吐非终态（或永远不结束）时，超时永远不会触发。
    """
    loop = asyncio.get_running_loop()
    while True:
        if done.is_set() and (
            events_finished.is_set()
            or (terminal_seen is not None and terminal_seen.get("seen"))
        ):
            return True
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(_WAIT_INTERVAL_S, remaining))


def _prompt_record(state: dict, run_id: str) -> dict | None:
    run = state.get("prompt_run")
    if isinstance(run, dict) and run.get("run_id") == run_id:
        return run
    return None


async def _finalize_prompt_run(
    *,
    agent: StudioAgent,
    project: Project,
    state: dict,
    run_id: str,
    prompt_thread: threading.Thread,
    done: threading.Event,
    events_finished: asyncio.Event,
    res: dict,
    errors: list[BaseException],
    terminal_seen: dict,
    thread_timeout_s: float,
    stop_grace_s: float,
    driver_task: asyncio.Task | None,
    started_at: float,
    stop_forwarding: threading.Event,
    cancel_driver_on_timeout: bool,
) -> None:
    """独立的终态收尾任务。

    它与 WS handler / 事件转发任务解耦：后者被取消时，本任务仍然继续等待
    工作线程、写 prompt_run、保存 spec 并投递终态。所有等待都是异步轮询，
    不在事件循环线程上做 Event.wait / Thread.join。
    """
    try:
        loop = asyncio.get_running_loop()
        deadline = started_at + thread_timeout_s
        finished = False
        timed_out = False

        # 线程一旦退出，就不该继续等完整 30 分钟预算——终态事件可能只是
        # 还排在慢发送/5s events() 超时后面。给一个短的有界 drain 窗口；
        # 仍无终态就按“线程结束但没有 terminal”失败，而不是拖到预算耗尽。
        while not done.is_set():
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(_WAIT_INTERVAL_S, remaining))
        if done.is_set():
            # 线程已结束，drain 窗口是额外预算，不能再被已过期的执行
            # deadline 截断。
            drain_deadline = loop.time() + min(stop_grace_s, 2.0)
            finished = await _wait_run_settled(
                done, events_finished, drain_deadline, terminal_seen
            )

        if not finished:
            if done.is_set():
                # 线程已退出且 drain 完仍无终态：停止转发，避免随后又补发
                # 一个与已写 prompt_run 矛盾的 terminal。
                stop_forwarding.set()
                if (
                    cancel_driver_on_timeout
                    and driver_task is not None
                    and not driver_task.done()
                ):
                    driver_task.cancel()
            else:
                timed_out = True
                # 先让转发循环在下一轮退出；直接取消“被调用方 await 的同一个
                # 协程”会让调用方收到 CancelledError，与终态任务解耦的语义
                # 相冲突。app 的 driver 是独立 task，额外允许取消以尽快释放
                # executor 里的 next()。
                stop_forwarding.set()
                try:
                    agent.abort()
                except Exception:
                    pass
                if (
                    cancel_driver_on_timeout
                    and driver_task is not None
                    and not driver_task.done()
                ):
                    driver_task.cancel()
                grace_deadline = loop.time() + stop_grace_s
                await _wait_run_settled(done, events_finished, grace_deadline)

        thread_alive = prompt_thread.is_alive()
        outcome: str
        err_msg: str | None = None
        if timed_out:
            # 超时后即使线程在 grace 内退出/abort 抛错，也不把本轮包装成
            # completed 或普通 prompt error：用户看到的必须是“预算耗尽”。
            outcome = "failed"
            if thread_alive:
                err_msg = (
                    f"prompt timed out after {thread_timeout_s:.0f}s; "
                    "thread still running after abort"
                )
            else:
                err_msg = f"prompt timed out after {thread_timeout_s:.0f}s"
        elif errors:
            outcome = "failed"
            err_msg = f"prompt error: {errors[0]}"
        elif res.get("aborted"):
            outcome = "cancelled"
        elif terminal_seen.get("seen") and not thread_alive:
            outcome = "completed"
        elif thread_alive:
            # 线程在 abort + grace 后仍然活着（例如卡在 Python 工具回调里）。
            # 不得伪装成 completed；保留 prompt_thread 供下一次启动检查。
            outcome = "failed"
            err_msg = (
                "prompt thread still running after "
                f"{thread_timeout_s + stop_grace_s:.0f}s; abort requested"
            )
        else:
            # 线程正常返回但事件流没有终态（渠道提前关闭/迭代器异常）。
            outcome = "failed"
            err_msg = "prompt ended without a terminal event"

        run = _prompt_record(state, run_id)
        if run is not None:
            run["status"] = outcome
            if err_msg:
                run["error"] = err_msg
            run["ended_at"] = time.time()

        await _send_live(
            state,
            {
                "type": "prompt_terminal",
                "run_id": run_id,
                "outcome": outcome,
                "error": err_msg,
            },
        )

        # 从 state 读取最新 spec（可能被 REST PUT 更新过）。保存失败必须
        # 让前端看见，不能把“执行完成”当成“修改已落盘”。
        spec = state.get("spec")
        saved = True
        save_error: str | None = None
        if spec is not None:
            try:
                # D1 的 save_spec 含文件/目录 fsync；留在事件循环上会冻结
                # 所有 WS/REST。项目锁保证 update_spec / session 提交 /
                # Play meta 不会与本提交交叉。新 prompt 仍会等待 finalizer。
                async with project_lock(state):
                    await asyncio.to_thread(project.save_spec, spec)
            except Exception as exc:  # noqa: BLE001
                saved = False
                save_error = f"spec save failed: {exc}"
                print(f"save_spec error: {exc}", file=sys.stderr)

        if spec is not None:
            try:
                payload = {
                    "type": "spec_updated",
                    "spec": spec.get_current_spec(),
                    "saved": saved,
                }
                await _send_live(state, payload)
            except Exception:
                pass
        if save_error is not None:
            await _send_live(
                state,
                {
                    "type": "spec_save_failed",
                    "run_id": run_id,
                    "message": save_error,
                },
            )

        if errors:
            await _send_live(
                state,
                {
                    "type": "error",
                    "message": f"prompt error: {errors[0]}",
                },
            )

        if state.get("prompt_thread") is prompt_thread and not thread_alive:
            state.pop("prompt_thread", None)

        # Settings/upload 在运行中不替换 harness，只记 pending；run 真正
        # 结束后在这里应用最新状态。若旧线程还活着（超时卡死），绝不换
        # harness，pending 留到下一次安全的启动点。
        if (
            state.get("harness_rebuild_pending")
            and not thread_alive
            and not play_is_active(state)
            and hasattr(agent, "rebuild")
        ):
            try:
                async with project_lock(state):
                    await asyncio.to_thread(agent.rebuild)
                state.pop("harness_rebuild_pending", None)
            except Exception as exc:  # noqa: BLE001
                print(f"pending harness rebuild failed: {exc}", file=sys.stderr)
    except asyncio.CancelledError:
        # finalizer 自身不应被取消；真被取消时保留记录，交给进程退出/人工处理。
        print("prompt finalizer cancelled", file=sys.stderr)
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"prompt finalizer error: {exc}", file=sys.stderr)
        run = _prompt_record(state, run_id)
        if run is not None and run.get("status") == "running":
            run["status"] = "failed"
            run["error"] = f"prompt finalizer error: {exc}"
            run["ended_at"] = time.time()


async def stop_active_prompt(
    state: dict,
    agent: StudioAgent,
    connection_id: str,
    *,
    grace_s: float = PROMPT_STOP_GRACE_S,
) -> str | None:
    """在启动新 prompt 前处理同项目的旧 run。

    返回 None 表示可以安全启动；返回字符串则调用方必须拒绝本次 prompt 并把
    原因发给前端。跨连接不抢占：A tab 的运行不能被 B tab 的 prompt 或 abort
    误杀。同连接允许 abort + 有界等待，等待不阻塞事件循环。
    """
    run = state.get("prompt_run")
    task = state.get("prompt_task")
    finalizer = state.get("prompt_finalizer")

    if prompt_is_active(state):
        owner = run.get("owner") if isinstance(run, dict) else None
        # 仍在线的另一个 tab 不能被抢占；原连接已经断开（owner 不在
        # ws_connections）时，重连连接可以 abort 这个孤儿 run，然后等待
        # 它安全结束再启动新一轮。
        if owner not in (None, connection_id) and owner_is_live(state, owner):
            return "此项目已有另一个连接在运行 prompt；请等待其结束，或在原连接中停止。"
        try:
            agent.abort()
        except Exception:
            pass
        pending = [
            candidate
            for candidate in (task, finalizer)
            if candidate is not None and not candidate.done()
        ]
        if pending:
            _, still_pending = await asyncio.wait(pending, timeout=grace_s)
            if still_pending:
                return "上一轮 prompt 尚未安全停止；为避免并发执行，本次请求已拒绝。"

    thread = state.get("prompt_thread")
    if thread is not None and thread.is_alive():
        return "上一轮 prompt 线程仍在运行；为避免并发执行，本次请求已拒绝。"
    return None


async def run_prompt_streaming(
    websocket: WebSocket,
    agent: StudioAgent,
    project: Project,
    text: str,
    state: dict,
    run_id: str,
    *,
    thread_timeout_s: float | None = None,
    stop_grace_s: float | None = None,
    cancel_driver_on_timeout: bool = False,
) -> None:
    """在后台线程运行 prompt，将事件推送到 WebSocket。

    生命周期归属：工作线程只产出结果；本函数负责事件转发；独立的 finalizer
    任务负责等待线程、写 state["prompt_run"]、保存 spec 与投递终态。
    socket 断开只影响投递，不影响执行结果。本协程被取消时 finalizer 仍继续。
    """
    if thread_timeout_s is None:
        thread_timeout_s = PROMPT_THREAD_TIMEOUT_S
    if stop_grace_s is None:
        stop_grace_s = PROMPT_STOP_GRACE_S
    loop = asyncio.get_running_loop()
    # 预算从本函数进入时开始，而不是等 events()/线程就绪之后。
    started_at = loop.time()

    harness = agent._harness
    if harness is None:
        run = _prompt_record(state, run_id)
        if run is not None:
            run["status"] = "failed"
            run["error"] = "agent harness not started"
            run["ended_at"] = time.time()
        await _send_live(
            state,
            {
                "type": "prompt_terminal",
                "run_id": run_id,
                "outcome": "failed",
                "error": "agent harness not started",
            },
        )
        await _send_live(
            state, {"type": "error", "message": "agent harness not started"}
        )
        return

    # 获取事件迭代器 — events() 返回同步迭代器
    # timeout_ms=5000: 单次 next 阻塞最多 5s
    # max_consecutive_timeouts=999: 高值，不因超时终止
    try:
        event_iter = harness.events(timeout_ms=5000, max_consecutive_timeouts=999)
    except Exception as exc:  # noqa: BLE001
        message = f"failed to subscribe harness events: {exc}"
        run = _prompt_record(state, run_id)
        if run is not None:
            run["status"] = "failed"
            run["error"] = message
            run["ended_at"] = time.time()
        await _send_live(
            state,
            {
                "type": "prompt_terminal",
                "run_id": run_id,
                "outcome": "failed",
                "error": message,
            },
        )
        await _send_live(state, {"type": "error", "message": message})
        return

    # 后台线程运行 prompt（阻塞调用）。结果分类进线程本地 res。
    errors: list[BaseException] = []
    done = threading.Event()
    res: dict = {"outcome": None, "error": None, "aborted": False}

    def _do_prompt() -> None:
        try:
            collected = agent.prompt(text, timeout_ms=120000)
            # abort() 使 prompt_and_collect 正常返回，末尾事件是 aborted——
            # 这是显式取消，不是失败。
            tail = [
                (e if isinstance(e, dict) else dict(e)).get("type")
                for e in collected
            ]
            res["aborted"] = "aborted" in tail
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            print(f"Prompt error: {exc}", file=sys.stderr)
        finally:
            done.set()

    prompt_thread = threading.Thread(target=_do_prompt, daemon=True)
    if _prompt_record(state, run_id) is not None:
        state["prompt_thread"] = prompt_thread
    try:
        prompt_thread.start()
    except Exception as exc:  # noqa: BLE001
        message = f"failed to start prompt thread: {exc}"
        if state.get("prompt_thread") is prompt_thread:
            state.pop("prompt_thread", None)
        run = _prompt_record(state, run_id)
        if run is not None:
            run["status"] = "failed"
            run["error"] = message
            run["ended_at"] = time.time()
        await _send_live(
            state,
            {
                "type": "prompt_terminal",
                "run_id": run_id,
                "outcome": "failed",
                "error": message,
            },
        )
        await _send_live(state, {"type": "error", "message": message})
        return

    terminal_seen = {"seen": False}
    events_finished = asyncio.Event()
    stop_forwarding = threading.Event()

    finalizer = asyncio.create_task(
        _finalize_prompt_run(
            agent=agent,
            project=project,
            state=state,
            run_id=run_id,
            prompt_thread=prompt_thread,
            done=done,
            events_finished=events_finished,
            res=res,
            errors=errors,
            terminal_seen=terminal_seen,
            thread_timeout_s=thread_timeout_s,
            stop_grace_s=stop_grace_s,
            driver_task=asyncio.current_task(),
            started_at=started_at,
            stop_forwarding=stop_forwarding,
            cancel_driver_on_timeout=cancel_driver_on_timeout,
        )
    )
    # 强引用：即使事件转发任务被取消，GC 也不能回收终态收尾任务。
    state["prompt_finalizer"] = finalizer

    def _clear_finalizer(task: asyncio.Task) -> None:
        if state.get("prompt_finalizer") is task:
            state.pop("prompt_finalizer", None)

    finalizer.add_done_callback(_clear_finalizer)

    try:
        while True:
            if stop_forwarding.is_set():
                break
            # 在 executor 中调用 next(event_iter)，不阻塞事件循环
            # 这样 WS 主循环可以处理 abort 消息
            try:
                event = await loop.run_in_executor(None, next, event_iter)
            except StopIteration:
                break
            except Exception as exc:
                print(f"Event iter error: {exc}", file=sys.stderr)
                break

            # next() 可能在 finalizer 结束 drain 之后才返回；此时不能再
            # 转发尾随事件，否则会和已写的 no-terminal 终态矛盾。
            if stop_forwarding.is_set():
                break

            if event is None:
                # 超时无事件 — 检查 prompt 线程是否结束
                if not prompt_thread.is_alive():
                    break
                continue

            # PyO3 对象可能不是 dict，统一转换
            if not isinstance(event, dict):
                try:
                    event = dict(event)
                except Exception:
                    event = {"type": "raw", "data": str(event)}

            event_type = event.get("type")
            # SDK 的 timeout 哨兵不是“事件流结束”本身。线程还活着时继续
            # 等下一批；线程已经退出但没 terminal，则停止转发，让 finalizer
            # 按“ended without a terminal event”收尾，而不是傻等 5s 一次。
            if event_type == "timeout":
                if not prompt_thread.is_alive():
                    break
                continue
            if event_type in _SKIP_TYPES:
                continue

            # 先记终态再发送：慢 socket 不能把“已完成的 run”拖成
            # no-terminal；发送本身仍有 10s 上限且不影响 finalizer。
            if event_type in _TERMINAL_TYPES:
                terminal_seen["seen"] = True
            await _send_live(state, event)
            if event_type in _TERMINAL_TYPES:
                break
    except asyncio.CancelledError:
        # 调用方取消只取消事件转发；finalizer 已在独立任务中继续。
        raise
    except Exception as exc:
        print(f"Stream error: {exc}", file=sys.stderr)
        await _send_live(
            state, {"type": "error", "message": f"stream error: {exc}"}
        )
    finally:
        events_finished.set()
        # 正常路径等待 finalizer 完成；取消路径下 shield 立即抛 CancelledError，
        # 但 finalizer 仍由 state 强引用继续运行。
        try:
            await asyncio.shield(finalizer)
        except asyncio.CancelledError:
            raise


async def finalize_play(
    websocket: WebSocket,
    project: Project,
    state: dict | None = None,
) -> None:
    """把 project 状态从 playing 收尾回 editing，并通知前端。

    幂等（只在真的还处于 playing 时才做）——同一次 Play 可能从两个地方
    触发收尾：run_play_streaming 自己（用户在跑的过程中点了 Stop，
    engine 已经是 cancelled 状态）或 app.py 的 "stop" 处理（用户在跑完
    之后才点 Stop，那时 run_play_streaming 早就退出了）。
    """
    if project.meta.get("status") != "playing":
        return
    lock = project_lock(state) if state is not None else asyncio.Lock()
    async with lock:
        if project.meta.get("status") != "playing":
            return
        old_status = project.meta.get("status")
        project.meta["status"] = "editing"
        try:
            # meta 写入含 fsync；绝不能留在事件循环线程上。
            await asyncio.to_thread(project._save_meta)
        except Exception as exc:  # noqa: BLE001
            project.meta["status"] = old_status
            try:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"保存 Play 结束状态失败：{exc}",
                        "source": "play",
                    }
                )
            except Exception:
                pass
            return
    try:
        await websocket.send_json({"type": "play_stopped"})
    except Exception:
        pass


async def run_play_streaming(
    websocket: WebSocket,
    play_session: PlaySession,
    project: Project,
    state: dict | None = None,
) -> None:
    """转发 Play 事件到 WebSocket。实现在 senza_studio_runtime.stream——
    Studio 和导出项目共用同一份协议，不留第二份拷贝（Phase 7）。

    这里只补上 Studio 专有的收尾：把项目状态从 playing 改回 editing。
    """
    async def _finish() -> None:
        await finalize_play(websocket, project, state)

    await _runtime_stream.run_play_streaming(websocket, play_session, _finish)
