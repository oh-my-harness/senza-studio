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


async def run_prompt_streaming(
    websocket: WebSocket,
    agent: StudioAgent,
    project: Project,
    text: str,
    state: dict,
    run_id: str,
) -> None:
    """在后台线程运行 prompt，将事件推送到 WebSocket。

    使用 harness.events() 迭代器 + run_in_executor 包装 next()，
    超时后返回 None，检查 prompt 线程是否存活，存活则继续等待。

    生命周期归属：prompt 执行结果由工作线程分类（res），本函数（事件循环侧）
    是 state["prompt_run"] 的唯一写入者——线程不直接写共享 state。socket
    断开只影响事件投递，不影响执行结果（线程独立运行到底）。
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

    # 后台线程运行 prompt（阻塞调用）。结果分类进线程本地 res；
    # state["prompt_run"] 由事件循环侧的 finally 发布（见下）。
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
    prompt_thread.start()

    loop = asyncio.get_event_loop()
    terminal_seen = False

    async def _send_live(state, obj: dict) -> None:
        """向 state 里当前活跃的 socket 投递一条消息（尽力而为）。
        本 socket 已死/被替换时静默放弃——结果已由 prompt_run 记录，
        新连接会在连接时收到 prompt_state 对账。"""
        target = state.get("ws_socket")
        try:
            if target is not None:
                await target.send_json(obj)
        except Exception:
            pass

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
                terminal_seen = True
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
        # 等待 prompt 线程结束（与 prompt timeout_ms=120000 对齐）。socket
        # 断开/任务被取消都不能打断这里对真结果的等待——执行结果由线程
        # 分类，本 finally 是唯一权威写入方（事件循环线程内，无锁竞争）。
        if not done.wait(timeout=125):
            # 线程仍未结束 — 强制中止
            try:
                agent.abort()
            except Exception:
                pass
            prompt_thread.join(timeout=10)

        # ---- 真实执行结果判定（不依赖 socket 状态）---------------------
        # 线程把结果留在 res 里：成功返回时 res["aborted"] 说明是显式取消。
        outcome: str
        err_msg: str | None = None
        if errors:
            outcome = "failed"
            err_msg = f"prompt error: {errors[0]}"
        elif res.get("aborted"):
            outcome = "cancelled"
        elif terminal_seen:
            outcome = "completed"
        else:
            # 迭代器耗尽但没见到终端事件（渠道提前关闭等）——以线程是否
            # 正常返回为准
            outcome = "cancelled" if res.get("aborted") else "completed"

        # run_id 守卫：本 run 已被更新的 prompt 覆盖时不再回写。
        run = state.get("prompt_run")
        if run is not None and run.get("run_id") == run_id:
            run["status"] = outcome
            if err_msg:
                run["error"] = err_msg
            run["ended_at"] = time.time()

        # 终态推送：发到项目当前活跃的 socket（跨 run 也投递——旧 run 的
        # 终态行必须追加到共享控制台；前端按 run_id 去重/判定是否归档当前
        # prompt 计时器）。先写 state 再 await：任务被取消时也能留下记录。
        try:
            await _send_live(
                state,
                {
                    "type": "prompt_terminal",
                    "run_id": run_id,
                    "outcome": outcome,
                    "error": err_msg,
                },
            )
        except Exception:
            pass

        # 从 state 读取最新 spec（可能被 REST PUT 更新过）
        spec = state["spec"]

        # 保存 spec（元 agent 可能通过工具修改了它）
        try:
            project.save_spec(spec)
        except Exception as exc:
            print(f"save_spec error: {exc}", file=sys.stderr)

        # 推送 spec_updated 事件
        try:
            await _send_live({"type": "spec_updated", "spec": spec.get_current_spec()})
        except Exception:
            pass

        # 如果 prompt 线程报错，推送 error 事件
        if errors:
            try:
                await _send_live(
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
    """转发 Play 事件到 WebSocket。实现在 senza_studio_runtime.stream——
    Studio 和导出项目共用同一份协议，不留第二份拷贝（Phase 7）。

    这里只补上 Studio 专有的收尾：把项目状态从 playing 改回 editing。
    """
    async def _finish() -> None:
        await finalize_play(websocket, project)

    await _runtime_stream.run_play_streaming(websocket, play_session, _finish)
