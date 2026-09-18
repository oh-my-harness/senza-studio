// studio_frontend/src/hooks/useProjectSocket.ts
import { useEffect } from "react";
import { api, createWebSocket } from "../api";
import { useStudioStore } from "../store";
import { PENDING_APPROVAL_ROUTE_KEY } from "../types";
import { splitToolCalls } from "../utils";

/** 项目 WebSocket 的生命周期 + 事件分发。
 *
 * 从 ChatPanel 里搬出来的（Phase 7 切片三）：导出项目跑的是 export 模式，
 * 根本不渲染对话面板，但 Play 的事件流还得照收。连接本来就不该属于某个面板
 * ——它是整个项目视图的东西。
 *
 * 只往 store 写，不碰任何组件局部 state；session 列表也一并提进了 store。
 */
export function useProjectSocket(projectId: string | null) {
  const setWs = useStudioStore((s) => s.setWs);
  const setStatus = useStudioStore((s) => s.setStatus);
  const setSpec = useStudioStore((s) => s.setSpec);
  const setRuntimeSpec = useStudioStore((s) => s.setRuntimeSpec);
  const setMessages = useStudioStore((s) => s.setMessages);
  const setToolCalls = useStudioStore((s) => s.setToolCalls);
  const addMessage = useStudioStore((s) => s.addMessage);
  const appendToLastAssistant = useStudioStore((s) => s.appendToLastAssistant);
  const addLog = useStudioStore((s) => s.addLog);
  const addToolCall = useStudioStore((s) => s.addToolCall);
  const startStep = useStudioStore((s) => s.startStep);
  const appendStepText = useStudioStore((s) => s.appendStepText);
  const finishStep = useStudioStore((s) => s.finishStep);
  const markAwaitingApproval = useStudioStore((s) => s.markAwaitingApproval);
  const setPausedStep = useStudioStore((s) => s.setPausedStep);
  const setEnginePaused = useStudioStore((s) => s.setEnginePaused);
  const setRunFinished = useStudioStore((s) => s.setRunFinished);
  const setStreaming = useStudioStore((s) => s.setStreaming);
  const failRunningSteps = useStudioStore((s) => s.failRunningSteps);
  const setSessions = useStudioStore((s) => s.setSessions);
  const setActiveSession = useStudioStore((s) => s.setActiveSession);

  // 连接 WebSocket
  useEffect(() => {
    if (!projectId) return;
    // React 18 StrictMode（开发模式）会在真正 mount 前先 mount → cleanup →
    // 再 mount 一遍，用来暴露 effect 清理的 bug。上一轮的 socket 常常在
    // handshake 完成前就被 cleanup 关闭，浏览器会当作异常断开触发
    // onerror，把"连接断开"消息永久插进聊天记录——即使随后真正的 socket
    // 完全正常。用这个标志位让"已经被替换掉的旧 socket"的事件直接忽略，
    // 而不是误当成当前连接的真实断开。
    let isCurrent = true;
    const socket = createWebSocket(projectId);
    setWs(socket);

    socket.onmessage = (e) => {
      if (!isCurrent) return;
      const event = JSON.parse(e.data);

      if (event.type === "text_delta" && event.step_id) {
        // Play 事件（带 step_id）——追加到对应 step 的 Game view 卡片
        appendStepText(event.step_id, event.text || "");
      } else if (event.type === "step_started") {
        startStep(event.step_id, event.step_name);
      } else if (event.type === "step_finished") {
        // checker step 卡在"等审批"——用 route_key 判断，不解析 reason 字符串
        // （paused 事件本身只有一句人类可读文案，没带 step_id）。这轮 run()
        // 只是提前退出，不是真的执行完了，所以不能用 finishStep（会把卡片
        // 标成 done，resume 之后同一个 step 的第二次 step_finished 就再也
        // 找不到 running 状态的卡片可更新）。
        const structured = event.structured as
          | {
              route_key?: string;
              _debug?: Record<string, unknown> | null;
              fields?: Record<string, unknown> | null;
            }
          | null
          | undefined;
        if (structured?.route_key === PENDING_APPROVAL_ROUTE_KEY) {
          markAwaitingApproval(event.step_id as string, event.output ?? "");
          setPausedStep(event.step_id as string);
        } else {
          finishStep(event.step_id, event.output, {
            route: structured?.route_key,
            debug: structured?._debug,
            fields: structured?.fields,
          });
          setPausedStep(null);
        }
      } else if (event.type === "paused") {
        // 不管暂停原因是 checker 审批还是控制条手动 Pause/Step，都置位——
        // 区分"是不是审批"用 pausedStepId（上面 step_finished 里单独维护）。
        setEnginePaused(true);
        addLog("info", `⏸ ${event.reason || "已暂停，等待人工审批"}`);
      } else if (event.type === "resumed") {
        setEnginePaused(false);
        addLog("info", "▶ 已恢复运行");
      } else if (event.type === "failed") {
        failRunningSteps();
        addLog("error", event.error || "工作流失败");
      } else if (event.type === "workflow_done") {
        // 跑完了（成功或失败）不自动退出 playing——留给用户自己看完结果
        // 再点 Stop。真正回到 editing 由下面的 play_stopped 触发。
        setRunFinished(event.state);
        // 终态意味着任何挂起的审批卡片都不再可操作（典型：执行时间护栏
        // 在 HITL 等待期间到期并取消了引擎）。不清掉的话，过期的审批按钮
        // 会留在界面上，点下去会被后端当作过期决定忽略。
        setPausedStep(null);
        setEnginePaused(false);
        if (event.state === "succeeded") {
          addLog("info", "✅ 运行成功完成");
        }
      } else if (event.type === "play_stopped") {
        setRunFinished(null);
        setPausedStep(null);
        setEnginePaused(false);
        setStatus("spec_ready");
      } else if (event.type === "text_delta") {
        // 流式文本追加到最近的 assistant 消息
        appendToLastAssistant(event.text || "");
      } else if (event.type === "message_start") {
        // 新消息开始 — 插入空 assistant 气泡，后续 text_delta 追加到它
        addMessage({ role: "assistant", content: "", timestamp: Date.now() });
      } else if (event.type === "tool_call_start") {
        // 工具调用不算对话内容，挪到底部面板的"工具调用"标签页，
        // 免得聊天记录被一堆调用/结果气泡塞满。
        addToolCall({
          content: `调用工具: ${event.tool_name}`,
          toolName: event.tool_name,
          timestamp: Date.now(),
        });
      } else if (event.type === "tool_result") {
        addToolCall({
          content: `结果: ${event.result}`,
          toolName: event.tool_name,
          timestamp: Date.now(),
        });
      } else if (event.type === "settled" || event.type === "aborted" || event.type === "error" || event.type === "agent_end") {
        setStreaming(false);
        if (event.type === "error") {
          // 这个 "error" 事件对话/Play 共用（run_prompt_streaming 和
          // run_play_streaming 都会发）——统一记到日志面板，不再插进聊天
          // 记录（插的假 assistant 气泡本来也不会被真实持久化，刷新就没了）。
          addLog("error", event.message || "发生错误");
        }
        // source: "play" 的 error 不该把 status 打回 spec_ready——Play 中途
        // 出错要留在 playing，让用户先看完 Game view 里的错误详情，自己点
        // Stop 才收尾（workflow_done 已经是这么处理的）。不这样做的话，
        // Play 出错时这条 error 事件会比 workflow_done 先到，用户还没来得
        // 及看输出就被直接退回编辑态（亲测复现过）。
        if (event.source !== "play") {
          setStatus("spec_ready");
        }
      } else if (event.type === "warning") {
        // 非致命提示（比如某个项目插件没加载成功）——记进日志面板即可，
        // 不改 status，Play 照常继续。
        addLog("error", event.message || "警告");
      } else if (event.type === "runtime_spec") {
        // Play 开始时后端下发的展开后 spec——审批按钮、ui.display、DAG
        // 高亮都按这份查，因为能力组件生成的 step 名不在编辑态 spec 里。
        if (event.spec) setRuntimeSpec(event.spec);
      } else if (event.type === "spec_updated") {
        if (event.spec) setSpec(event.spec);
      } else if (event.type === "session_switched") {
        const sid = event.session_id as string;
        setActiveSession(sid);
        setSessions((prev) => (prev.includes(sid) ? prev : [...prev, sid]));
        api
          .getMessages(projectId)
          .then((msgs) => {
            const { chat, tools } = splitToolCalls(msgs);
            setMessages(chat);
            setToolCalls(tools);
          })
          .catch(console.error);
      }
    };

    socket.onclose = () => {
      if (!isCurrent) return;
      setStreaming(false);
      setStatus("idle");
    };

    socket.onerror = () => {
      if (!isCurrent) return;
      setStreaming(false);
      setStatus("idle");
      addLog("error", "WebSocket 连接断开，请刷新页面重试");
    };

    return () => {
      isCurrent = false;
      socket.close();
    };
  }, [projectId]);
}
