"""Play 的 WebSocket 事件协议（Phase 7 切片三）。

从 studio_backend/ws.py 搬过来的：Studio 的 Play 和导出项目的 serve 用的是
**同一份**协议实现。各写一份的话，两边的事件流迟早长得不一样——而"导出项目行为
和 Studio 里一致"正是这一阶段的验收标准。

不认识 Studio 的 Project：收尾动作（Studio 那边要把项目状态从 playing 改回
editing）作为 on_finished 回调传进来，导出项目不传。
"""
from __future__ import annotations

import asyncio
import sys
from typing import Awaitable, Callable

from fastapi import WebSocket

from .play import PlaySession

_TERMINAL_TYPES = frozenset({"settled", "aborted", "error", "agent_end"})
_SKIP_TYPES = frozenset({"timeout"})

# "跑完了"这件事没有事件通知——只能靠 timeout 哨兵醒过来时发现后台线程死了
# （见下面循环里的注释）。所以这个间隔就是**终态的发现延迟**：设成 5s 的时候，
# 导出产品里最后一张结果卡片已经显示出来了，底下的按钮还有 5.4 秒写着"取消"
# 而不是"再来一次"（实测）。
#
# 两个值相乘是"允许一直没有任何事件"的总时长（≈83 分钟），这是给真实 LLM
# 长时间不出字留的余量。缩短间隔必须同比放大次数，否则会把一个跑得慢但正常
# 的 step 误判成卡死。
POLL_INTERVAL_MS = 250
MAX_SILENT_POLLS = 20_000


async def run_play_streaming(
    websocket: WebSocket,
    play_session: PlaySession,
    on_finished: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """转发 Play 运行的 WorkflowEvent 到 WebSocket。

    与 run_prompt_streaming 同一模式：用 run_in_executor 包装 subscribe() 的
    next()，避免阻塞 WS 主循环。必须先订阅再启动后台线程（play_session.start()）
    ——tokio broadcast 不缓冲订阅前发出的事件，晚订阅会丢掉跑得很快的
    step（没有真实 LLM 调用、立刻 fail）产生的早期事件。
    """
    # 先把这次运行真正执行的 spec 发给前端（能力组件已展开）。前端的审批
    # 按钮、ui.display 分派、DAG 高亮都是按 step 名去 spec 里查的，而组件
    # 展开出来的 step 名在编辑态 spec 里不存在——不发这个的话，跑到组件生成
    # 的 checker 上会显示"没有配置 next_on_* 路由"，用户点不了批准，整个
    # Play 卡死（用户实测踩到过）。
    if play_session.runtime_spec is not None:
        try:
            await websocket.send_json(
                {"type": "runtime_spec", "spec": play_session.runtime_spec}
            )
        except Exception:  # noqa: BLE001
            pass

    # 插件加载失败是非致命的（插件是加法），但必须让用户看见：不报的话
    # agent 只是莫名其妙少了一批工具，没有任何线索。
    for message in play_session.plugin_errors:
        try:
            await websocket.send_json(
                {"type": "warning", "message": f"插件未加载 — {message}"}
            )
        except Exception:  # noqa: BLE001
            pass

    event_iter = play_session.events(
        timeout_ms=POLL_INTERVAL_MS, max_consecutive_timeouts=MAX_SILENT_POLLS
    )
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
                # max_consecutive_timeouts 耗尽。醒得越快，用户看到
                # "跑完了"越及时——POLL_INTERVAL_MS 就是这个延迟。
                #
                # 但线程死了不等于跑完了——checker 等人工审批时，run()
                # 因为 WorkflowPausedError 也会让线程退出，这时 engine 状态
                # 是 "paused"，不是终态。同一个 subscribe() 迭代器在
                # submit_decision() 重新 run() 之后还能继续收到事件（亲测
                # 行为），所以这里不能 break，得继续等，直到真的有终态。
                thread_dead = not (play_session._thread and play_session._thread.is_alive())
                if thread_dead and play_session.state() != "paused":
                    break
                continue

            await websocket.send_json(event)

            if etype in ("failed", "cancelled"):
                break
    except Exception as exc:
        print(f"Play stream error: {exc}", file=sys.stderr)
        try:
            # source: "play" ——ChatPanel 的通用 error 处理器（对话/Play 共用）
            # 看到这个字段就不会把 status 打回 spec_ready：Play 中途出错要
            # 留在 playing，让用户看完 Game view 里的错误详情再自己点 Stop，
            # 不能一收到 error 事件就立刻把整个 Play 视图切走（亲测复现过
            # 这个 bug：没有这个字段时，error 事件比 workflow_done 先到，
            # 用户还没来得及看输出就被退回编辑态）。
            await websocket.send_json(
                {"type": "error", "message": f"play stream error: {exc}", "source": "play"}
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
                    {"type": "error", "message": str(play_session.run_error), "source": "play"}
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
            if on_finished is not None:
                await on_finished()
