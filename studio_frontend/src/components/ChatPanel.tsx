// studio_frontend/src/components/ChatPanel.tsx
import { useState, useRef, useEffect } from "react";
import { useStudioStore } from "../store";
import { createWebSocket } from "../api";

export default function ChatPanel({ projectId }: { projectId: string }) {
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const messages = useStudioStore((s) => s.messages);
  const addMessage = useStudioStore((s) => s.addMessage);
  const appendToLastAssistant = useStudioStore((s) => s.appendToLastAssistant);
  const setSpec = useStudioStore((s) => s.setSpec);
  const setStatus = useStudioStore((s) => s.setStatus);
  const ws = useStudioStore((s) => s.ws);
  const setWs = useStudioStore((s) => s.setWs);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

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

      if (event.type === "text_delta") {
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

  return (
    <div className="flex flex-col h-full w-96 border-r border-gray-200 bg-white">
      <div className="px-4 py-3 border-b border-gray-200 font-medium text-gray-700">
        对话
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
