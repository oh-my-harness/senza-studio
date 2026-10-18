// studio_frontend/src/components/BottomPanel.tsx
import { useState } from "react";
import { useStudioStore } from "../store";

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("zh-CN", { hour12: false });
}

type Tab = "tools" | "logs";

export default function BottomPanel() {
  const toolCalls = useStudioStore((s) => s.toolCalls);
  const logs = useStudioStore((s) => s.logs);
  const clearLogs = useStudioStore((s) => s.clearLogs);
  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState<Tab>("tools");

  const errorCount = logs.filter((l) => l.level === "error").length;

  return (
    <div className="border-t border-gray-200 bg-white">
      <div className="w-full flex items-center justify-between px-2">
        <div className="flex items-center">
          <button
            onClick={() => {
              setTab("tools");
              setExpanded(true);
            }}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs border-b-2 ${
              expanded && tab === "tools"
                ? "border-blue-500 text-blue-600 font-medium"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            <span>工具调用</span>
            {toolCalls.length > 0 && (
              <span className="rounded-full bg-gray-100 text-gray-600 px-1.5">
                {toolCalls.length}
              </span>
            )}
          </button>
          <button
            onClick={() => {
              setTab("logs");
              setExpanded(true);
            }}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs border-b-2 ${
              expanded && tab === "logs"
                ? "border-blue-500 text-blue-600 font-medium"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            <span>日志</span>
            {logs.length > 0 && (
              <span
                className={`rounded-full px-1.5 ${
                  errorCount > 0
                    ? "bg-red-100 text-red-700"
                    : "bg-gray-100 text-gray-600"
                }`}
              >
                {logs.length}
              </span>
            )}
          </button>
        </div>
        <div className="flex items-center gap-2">
          {expanded && tab === "logs" && logs.length > 0 && (
            <button
              onClick={clearLogs}
              className="text-xs text-gray-400 hover:text-gray-700"
            >
              清空
            </button>
          )}
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-xs text-gray-400 hover:text-gray-700 px-2 py-1.5"
          >
            {expanded ? "▼ 收起" : "▲ 展开"}
          </button>
        </div>
      </div>
      {expanded && (
        <div className="max-h-40 overflow-y-auto border-t border-gray-100 px-4 py-2 space-y-1">
          {tab === "tools" &&
            (toolCalls.length === 0 ? (
              <div className="text-xs text-gray-400">暂无工具调用</div>
            ) : (
              toolCalls.map((call, i) => (
                <div key={i} className="text-xs font-mono text-gray-600">
                  <span className="text-gray-400">[{formatTime(call.timestamp)}]</span>{" "}
                  {call.content}
                </div>
              ))
            ))}
          {tab === "logs" &&
            (logs.length === 0 ? (
              <div className="text-xs text-gray-400">暂无日志</div>
            ) : (
              logs.map((log, i) => (
                <div
                  key={i}
                  className={`text-xs font-mono ${
                    log.level === "error" ? "text-red-600" : "text-gray-600"
                  }`}
                >
                  <span className="text-gray-400">[{formatTime(log.timestamp)}]</span>{" "}
                  {log.message}
                </div>
              ))
            ))}
        </div>
      )}
    </div>
  );
}
