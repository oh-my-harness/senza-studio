// studio_frontend/src/components/ChatPanel.tsx
import { useState, useRef, useEffect } from "react";
import { useStudioStore } from "../store";
import { createWebSocket, api } from "../api";
import Markdown from "./Markdown";
import { splitToolCalls } from "../utils";
import { PENDING_APPROVAL_ROUTE_KEY } from "../types";

const MAX_TEXTAREA_HEIGHT = 160; // px，约 6~7 行，超过就交给滚动条

export default function ChatPanel({ projectId }: { projectId: string }) {
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sessions, setSessions] = useState<string[]>([]);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const messages = useStudioStore((s) => s.messages);
  const addMessage = useStudioStore((s) => s.addMessage);
  const setMessages = useStudioStore((s) => s.setMessages);
  const appendToLastAssistant = useStudioStore((s) => s.appendToLastAssistant);
  const setSpec = useStudioStore((s) => s.setSpec);
  const setStatus = useStudioStore((s) => s.setStatus);
  const ws = useStudioStore((s) => s.ws);
  const setWs = useStudioStore((s) => s.setWs);
  const startStep = useStudioStore((s) => s.startStep);
  const appendStepText = useStudioStore((s) => s.appendStepText);
  const finishStep = useStudioStore((s) => s.finishStep);
  const failRunningSteps = useStudioStore((s) => s.failRunningSteps);
  const setRunFinished = useStudioStore((s) => s.setRunFinished);
  const addLog = useStudioStore((s) => s.addLog);
  const addToolCall = useStudioStore((s) => s.addToolCall);
  const setToolCalls = useStudioStore((s) => s.setToolCalls);
  const setPausedStep = useStudioStore((s) => s.setPausedStep);
  const markAwaitingApproval = useStudioStore((s) => s.markAwaitingApproval);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 加载 session 列表
  useEffect(() => {
    api
      .listSessions(projectId)
      .then(({ sessions, active }) => {
        setSessions(sessions);
        setActiveSession(active);
      })
      .catch(console.error);
  }, [projectId]);

  // 连接 WebSocket
  useEffect(() => {
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
          | { route_key?: string; _debug?: Record<string, unknown> | null }
          | null
          | undefined;
        if (structured?.route_key === PENDING_APPROVAL_ROUTE_KEY) {
          markAwaitingApproval(event.step_id as string, event.output ?? "");
          setPausedStep(event.step_id as string);
        } else {
          finishStep(event.step_id, event.output, {
            route: structured?.route_key,
            debug: structured?._debug,
          });
          setPausedStep(null);
        }
      } else if (event.type === "paused") {
        addLog("info", `⏸ ${event.reason || "已暂停，等待人工审批"}`);
      } else if (event.type === "resumed") {
        addLog("info", "▶ 已恢复运行");
      } else if (event.type === "failed") {
        failRunningSteps();
        addLog("error", event.error || "工作流失败");
      } else if (event.type === "workflow_done") {
        // 跑完了（成功或失败）不自动退出 playing——留给用户自己看完结果
        // 再点 Stop。真正回到 editing 由下面的 play_stopped 触发。
        setRunFinished(event.state);
        if (event.state === "succeeded") {
          addLog("info", "✅ 运行成功完成");
        }
      } else if (event.type === "play_stopped") {
        setRunFinished(null);
        setPausedStep(null);
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
        setStatus("spec_ready");
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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // 输入框按内容自动长高，封顶后交给 overflow-y-auto 滚动，而不是无限撑高。
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT)}px`;
  }, [input]);

  // 提交后到第一个 token 到达前有个空档——纯 streaming 状态看不出区别，
  // 加个"思考中"指示。一旦助手气泡有内容了，流式文字本身就是反馈，不再
  // 需要这个指示。
  const lastMessage = messages[messages.length - 1];
  const waitingForResponse =
    streaming && (!lastMessage || lastMessage.role !== "assistant" || !lastMessage.content);

  const send = () => {
    if (!input.trim() || !ws || streaming) return;
    addMessage({ role: "user", content: input, timestamp: Date.now() });
    ws.send(JSON.stringify({ type: "prompt", text: input }));
    setInput("");
    setStreaming(true);
    setStatus("conversing");
  };

  const switchSession = (sid: string) => {
    if (!ws || streaming || sid === activeSession) return;
    ws.send(JSON.stringify({ type: "switch_session", session_id: sid }));
  };

  const newSession = async () => {
    if (!ws || streaming) return;
    const { session_id } = await api.createSession(projectId);
    setSessions((prev) => [...prev, session_id]);
    ws.send(JSON.stringify({ type: "switch_session", session_id }));
  };

  return (
    <div className="flex flex-col h-full w-full border-r border-gray-200 bg-white">
      <div className="px-4 py-3 border-b border-gray-200 font-medium text-gray-700 flex items-center justify-between gap-2">
        <span>对话</span>
        <div className="flex items-center gap-1">
          <select
            value={activeSession ?? ""}
            onChange={(e) => switchSession(e.target.value)}
            disabled={streaming || sessions.length === 0}
            className="rounded border border-gray-200 text-xs px-1 py-0.5 text-gray-500 bg-white disabled:opacity-50 max-w-[8rem]"
          >
            {sessions.map((sid) => (
              <option key={sid} value={sid}>
                {sid}
              </option>
            ))}
          </select>
          <button
            onClick={newSession}
            disabled={streaming}
            title="新建对话"
            className="rounded border border-gray-200 text-xs px-2 py-0.5 text-gray-500 hover:bg-gray-50 disabled:opacity-50"
          >
            +
          </button>
        </div>
      </div>
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">
        {messages.map((m, i) => (
          <div
            key={i}
            className={`rounded-lg p-3 text-sm ${
              m.role === "user"
                ? "bg-blue-50 text-blue-900 ml-8"
                : "bg-gray-50 text-gray-800 mr-8"
            }`}
          >
            {m.role === "assistant" ? <Markdown text={m.content} /> : m.content}
          </div>
        ))}
        {waitingForResponse && (
          <div className="flex items-center gap-2 text-gray-400 text-sm mr-8 px-1">
            <svg
              className="animate-spin h-4 w-4"
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99"
              />
            </svg>
            <span>思考中…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div className="p-4 border-t border-gray-200">
        <div className="flex gap-2 items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="描述你想要的 Agent 流程…（Shift+Enter 换行）"
            rows={1}
            style={{ maxHeight: MAX_TEXTAREA_HEIGHT }}
            className="flex-1 resize-none overflow-y-auto rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:border-blue-400"
            disabled={streaming}
          />
          <button
            onClick={send}
            disabled={streaming || !input.trim()}
            className="rounded-lg bg-blue-500 px-4 py-2 text-sm text-white hover:bg-blue-600 disabled:opacity-50"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}
