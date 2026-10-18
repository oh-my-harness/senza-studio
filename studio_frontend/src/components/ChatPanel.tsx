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
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messages = useStudioStore((s) => s.messages);
  const addMessage = useStudioStore((s) => s.addMessage);
  const setMessages = useStudioStore((s) => s.setMessages);
  const appendToLastAssistant = useStudioStore((s) => s.appendToLastAssistant);
  const setSpec = useStudioStore((s) => s.setSpec);
  const setRuntimeSpec = useStudioStore((s) => s.setRuntimeSpec);
  const setStatus = useStudioStore((s) => s.setStatus);
  const ws = useStudioStore((s) => s.ws);
  const sessions = useStudioStore((s) => s.sessions);
  const activeSession = useStudioStore((s) => s.activeSession);
  const streaming = useStudioStore((s) => s.streaming);
  const setSessions = useStudioStore((s) => s.setSessions);
  const setActiveSession = useStudioStore((s) => s.setActiveSession);
  const setStreaming = useStudioStore((s) => s.setStreaming);
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
  const setEnginePaused = useStudioStore((s) => s.setEnginePaused);
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

  // 上传即解析：后端存原文 → 立刻 ingest → 摘要进 system prompt。这里把摘要
  // 也作为一条消息显示出来，用户能立刻确认"它读到的是不是我想给的东西"。
  const upload = async (file: File) => {
    setUploading(true);
    try {
      const result = await api.uploadDocument(projectId, file);
      addMessage({
        role: "tool",
        toolName: result.ok ? "上传文档" : "上传文档（解析失败）",
        content: `${result.name}\n${result.summary}`,
        timestamp: Date.now(),
      });
      if (!result.ok) addLog("error", `${result.name}: ${result.summary}`);
    } catch (e) {
      addLog("error", `上传失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setUploading(false);
      // 清空 value，否则连续传同一个文件不会触发 change
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

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
                : m.role === "tool"
                  ? "bg-amber-50 text-amber-900 border border-amber-200"
                  : "bg-gray-50 text-gray-800 mr-8"
            }`}
          >
            {/* tool 气泡是系统提示（比如"上传文档"的解析摘要），不是助手说的话
                ——不区分样式的话它跟助手回复长得一模一样，用户会以为是模型
                在讲话。另外这类内容自带换行，要 pre-wrap 才不会挤成一行。 */}
            {m.role === "tool" ? (
              <>
                {m.toolName && (
                  <div className="text-xs font-medium text-amber-700 mb-1">
                    {m.toolName}
                  </div>
                )}
                <div className="whitespace-pre-wrap break-words">{m.content}</div>
              </>
            ) : m.role === "assistant" ? (
              <Markdown text={m.content} />
            ) : (
              m.content
            )}
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
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            accept=".xlsx,.xlsm,.csv,.pdf,.md,.txt,.json,.yaml,.yml"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) upload(file);
            }}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={streaming || uploading}
            title="上传文档（Excel / CSV / PDF / 文本 / JSON / YAML）"
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-50"
          >
            {uploading ? "解析中…" : "📎"}
          </button>
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
