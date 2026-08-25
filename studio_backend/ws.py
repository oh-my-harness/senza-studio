"""WebSocket 连接管理 + 事件转发。

将元 agent 的 streaming 事件转发给前端 WebSocket。
"""
from __future__ import annotations

import asyncio
import sys
import threading
from typing import Any

from fastapi import WebSocket

from .agent import StudioAgent
from .project import Project
from .spec import Spec

# 事件类型标记一轮对话终止（SDK _TERMINAL_TYPES 的子集，适用于 agent harness）
_TERMINAL_TYPES = frozenset({"settled", "aborted", "error", "agent_end"})


async def run_prompt_streaming(
    websocket: WebSocket,
    agent: StudioAgent,
    project: Project,
    spec: Spec,
    text: str,
) -> None:
    """在后台线程运行 prompt，将事件推送到 WebSocket。

    元 agent 的 prompt_and_collect 是阻塞调用。
    用 senza.stream_events() + 后台 prompt 线程实现 streaming：
    stream_events 内部用 asyncio.to_thread 包装 next(it)，释放 GIL，
    使事件循环保持响应。
    """
    import senza

    harness = agent._harness
    if harness is None:
        await websocket.send_json(
            {"type": "error", "message": "agent harness not started"}
        )
        return

    # 获取事件迭代器（harness.events(timeout_ms=..., max_consecutive_timeouts=...)）
    # stream_events 是 async generator，内部用 to_thread 包装 next(it)
    event_iter = senza.stream_events(harness, timeout_ms=2000, max_consecutive_timeouts=2)

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

    # 迭代事件并推送
    try:
        async for event in event_iter:
            # PyO3 对象可能不是 dict，统一转换
            if not isinstance(event, dict):
                try:
                    event = dict(event)
                except Exception:
                    event = {"type": "raw", "data": str(event)}

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
        # 等待 prompt 线程结束
        done.wait(timeout=60)
        prompt_thread.join(timeout=5)

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
