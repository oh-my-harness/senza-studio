"""WebSocket 连接管理 + 事件转发。

将元 agent 的 streaming 事件转发给前端 WebSocket。
"""
from __future__ import annotations

import asyncio
import sys
import threading

from fastapi import WebSocket

from .agent import StudioAgent
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
