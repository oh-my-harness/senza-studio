"""WebSocket 连接管理 + 事件转发。

将元 agent 的 streaming 事件转发给前端 WebSocket。
"""
from __future__ import annotations

import asyncio
import sys
import threading

from fastapi import WebSocket

from .agent import StudioAgent
from .play import PlaySession
from .project import Project


# 事件类型标记一轮对话终止（SDK _TERMINAL_TYPES 的子集，适用于 agent harness）
_TERMINAL_TYPES = frozenset({"settled", "aborted", "error", "agent_end"})

# SDK 内部事件类型，不应转发给前端
_SKIP_TYPES = frozenset({"timeout"})


async def run_prompt_streaming(
    websocket: WebSocket,
    agent: StudioAgent,
    project: Project,
    text: str,
    state: dict,
) -> None:
    """在后台线程运行 prompt，将事件推送到 WebSocket。

    使用 harness.events() 迭代器 + run_in_executor 包装 next()，
    超时后返回 None，检查 prompt 线程是否存活，存活则继续等待。
    """
    harness = agent._harness
    if harness is None:
        await websocket.send_json(
            {"type": "error", "message": "agent harness not started"}
        )
        return

    # 获取事件迭代器 — events() 返回同步迭代器
    # timeout_ms=5000: 单次 next 阻塞最多 5s
    # max_consecutive_timeouts=999: 高值，不因超时终止
    event_iter = harness.events(timeout_ms=5000, max_consecutive_timeouts=999)

    # 后台线程运行 prompt（阻塞调用）
    errors: list[BaseException] = []
    done = threading.Event()

    def _do_prompt() -> None:
        try:
            agent.prompt(text, timeout_ms=120000)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            print(f"Prompt error: {exc}", file=sys.stderr)
        finally:
            done.set()

    prompt_thread = threading.Thread(target=_do_prompt, daemon=True)
    prompt_thread.start()

    loop = asyncio.get_event_loop()

    # 迭代事件并推送
    try:
        while True:
            # 在 executor 中调用 next(event_iter)，不阻塞事件循环
            # 这样 WS 主循环可以处理 abort 消息
            try:
                event = await loop.run_in_executor(None, next, event_iter)
            except StopIteration:
                break
            except Exception as exc:
                print(f"Event iter error: {exc}", file=sys.stderr)
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

            # 过滤 SDK 内部事件（timeout 等）
            if event.get("type") in _SKIP_TYPES:
                continue

            await websocket.send_json(event)

            if event.get("type") in _TERMINAL_TYPES:
                break
    except Exception as exc:
        print(f"Stream error: {exc}", file=sys.stderr)
        try:
            await websocket.send_json(
                {"type": "error", "message": f"stream error: {exc}"}
            )
        except Exception:
            pass
    finally:
        # 等待 prompt 线程结束（与 prompt timeout_ms=120000 对齐）
        if not done.wait(timeout=125):
            # 线程仍未结束 — 强制中止
            try:
                agent.abort()
            except Exception:
                pass
            prompt_thread.join(timeout=10)

        # 从 state 读取最新 spec（可能被 REST PUT 更新过）
        spec = state["spec"]

        # 保存 spec（元 agent 可能通过工具修改了它）
        try:
            project.save_spec(spec)
        except Exception as exc:
            print(f"save_spec error: {exc}", file=sys.stderr)

        # 推送 spec_updated 事件
        try:
            await websocket.send_json(
                {"type": "spec_updated", "spec": spec.get_current_spec()}
            )
        except Exception:
            pass

        # 如果 prompt 线程报错，推送 error 事件
        if errors:
            try:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"prompt error: {errors[0]}",
                    }
                )
            except Exception:
                pass


async def finalize_play(websocket: WebSocket, project: Project) -> None:
    """把 project 状态从 playing 收尾回 editing，并通知前端。

    幂等（只在真的还处于 playing 时才做）——同一次 Play 可能从两个地方
    触发收尾：run_play_streaming 自己（用户在跑的过程中点了 Stop，
    engine 已经是 cancelled 状态）或 app.py 的 "stop" 处理（用户在跑完
    之后才点 Stop，那时 run_play_streaming 早就退出了）。
    """
    if project.meta.get("status") != "playing":
        return
    project.meta["status"] = "editing"
    project._save_meta()
    try:
        await websocket.send_json({"type": "play_stopped"})
    except Exception:
        pass


async def run_play_streaming(
    websocket: WebSocket,
    play_session: PlaySession,
    project: Project,
) -> None:
    """转发 Play 运行的 WorkflowEvent 到 WebSocket。

    与 run_prompt_streaming 同一模式：用 run_in_executor 包装 subscribe() 的
    next()，避免阻塞 WS 主循环。必须先订阅再启动后台线程（play_session.start()）
    ——tokio broadcast 不缓冲订阅前发出的事件，晚订阅会丢掉跑得很快的
    step（没有真实 LLM 调用、立刻 fail）产生的早期事件。
    """
    event_iter = play_session.events(timeout_ms=5000, max_consecutive_timeouts=999)
    play_session.start()
    loop = asyncio.get_event_loop()

    try:
        while True:
            try:
                event = await loop.run_in_executor(None, next, event_iter)
            except StopIteration:
                break
            except Exception as exc:
                print(f"Play event iter error: {exc}", file=sys.stderr)
                break

            if event is None:
                break

            if not isinstance(event, dict):
                try:
                    event = dict(event)
                except Exception:
                    event = {"type": "raw", "data": str(event)}

            etype = event.get("type")
            if etype in _SKIP_TYPES:
                # WorkflowEventIterator 的 "timeout" 是逐次超时的哨兵 dict，
                # 不是 None——真正的 None 只在 channel 关闭或 999 次连续超时
                # 后才出现。跑得很快、没有真实 LLM 调用的 step（比如直接
                # fail 的 checker）可能后台线程已经结束但事件流早就抽干，
                # 只在这里检查线程是否还活着才能及时退出，否则要傻等到
                # max_consecutive_timeouts 耗尽（最多 999*5s）。
                if not (play_session._thread and play_session._thread.is_alive()):
                    break
                continue

            await websocket.send_json(event)

            if etype in ("failed", "cancelled"):
                break
    except Exception as exc:
        print(f"Play stream error: {exc}", file=sys.stderr)
        try:
            await websocket.send_json(
                {"type": "error", "message": f"play stream error: {exc}"}
            )
        except Exception:
            pass
    finally:
        if play_session._thread is not None:
            play_session._thread.join(timeout=10)
        state = play_session.state()
        # engine.run() 在 workflow 失败时 raise——PlaySession 把它捕获存到
        # run_error 而不是让线程崩溃。这里确保前端总能拿到清晰的错误信息，
        # 不依赖 WorkflowEvent::Failed 广播是否先一步送达。
        if play_session.run_error is not None:
            try:
                await websocket.send_json(
                    {"type": "error", "message": str(play_session.run_error)}
                )
            except Exception:
                pass
        try:
            await websocket.send_json({"type": "workflow_done", "state": state})
        except Exception:
            pass
        # 运行成功/失败结束——不自动收尾，留在 playing 让用户看完结果再
        # 自己点 Stop。只有 cancelled（用户在跑的过程中就点了 Stop）才
        # 立刻收尾，因为这次 workflow_done 本身就是那次 Stop 的直接结果。
        if state == "cancelled":
            await finalize_play(websocket, project)
