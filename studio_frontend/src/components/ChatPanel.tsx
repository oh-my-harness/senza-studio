// studio_frontend/src/components/ChatPanel.tsx
import { useState, useRef, useEffect } from "react";
import { useStudioStore } from "../store";
import { createWebSocket, api } from "../api";

export default function ChatPanel({
  projectId,
  collapsed = false,
}: {
  projectId: string;
  collapsed?: boolean;
}) {
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
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

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
        finishStep(event.step_id, event.output);
      } else if (event.type === "failed") {
        failRunningSteps();
      } else if (event.type === "workflow_done") {
        setStatus("spec_ready");
      } else if (event.type === "text_delta") {
        // 流式文本追加到最近的 assistant 消息
        appendToLastAssistant(event.text || "");
      } else if (event.type === "message_start") {
        // 新消息开始 — 插入空 assistant 气泡，后续 text_delta 追加到它
        addMessage({ role: "assistant", content: "", timestamp: Date.now() });
      } else if (event.type === "tool_call_start") {
        addMessage({
          role: "tool",
          content: `调用工具: ${event.tool_name}`,
          toolName: event.tool_name,
          timestamp: Date.now(),
        });
      } else if (event.type === "tool_result") {
        addMessage({
          role: "tool",
          content: `结果: ${event.result}`,
          toolName: event.tool_name,
          timestamp: Date.now(),
        });
      } else if (event.type === "settled" || event.type === "aborted" || event.type === "error" || event.type === "agent_end") {
        setStreaming(false);
        if (event.type === "error") {
          addMessage({ role: "assistant", content: `⚠️ ${event.message || "发生错误"}`, timestamp: Date.now() });
        }
        setStatus("spec_ready");
      } else if (event.type === "spec_updated") {
        if (event.spec) setSpec(event.spec);
      } else if (event.type === "session_switched") {
        const sid = event.session_id as string;
        setActiveSession(sid);
        setSessions((prev) => (prev.includes(sid) ? prev : [...prev, sid]));
        api.getMessages(projectId).then(setMessages).catch(console.error);
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
      addMessage({ role: "assistant", content: "⚠️ 连接断开，请刷新页面重试", timestamp: Date.now() });
    };

    return () => {
      isCurrent = false;
      socket.close();
    };
  }, [projectId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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
    <div
      className={`flex flex-col h-full border-r border-gray-200 bg-white ${
        collapsed ? "w-64" : "w-96"
      }`}
    >
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
                : m.role === "tool"
                ? "bg-gray-50 text-gray-600 text-xs font-mono"
                : "bg-gray-50 text-gray-800 mr-8"
            }`}
          >
            {m.content}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <div className="p-4 border-t border-gray-200">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
            placeholder="描述你想要的 Agent 流程…"
            className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:border-blue-400"
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
