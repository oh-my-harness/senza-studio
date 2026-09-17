// studio_frontend/src/components/BottomPanel.tsx
import { useState } from "react";
import { useStudioStore } from "../store";
import type { ExecRow } from "../types";

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("zh-CN", { hour12: false });
}

type Tab = "tools" | "logs" | "exec";
// args 解析永远不抛——坏 JSON/非对象/超长都按原始字符串展示。返回
// [展示文本, 是否有效 JSON]。
function parseArgs(raw: string | null): [string, boolean] {
  if (raw === null) return ["(未收到参数)", false];
  if (raw.length > 2000) return [raw.slice(0, 2000) + "…(截断)", true];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed !== null && typeof parsed === "object") {
      return [JSON.stringify(parsed, null, 1), true];
    }
    return [String(parsed), true];
  } catch {
    return [raw, false];
  }
}

const PHASE_LABEL: Record<string, string> = {
  calling: "调用中",
  executing: "执行中",
  done: "完成",
  failed: "失败",
};

const PHASE_STYLE: Record<string, string> = {
  calling: "bg-amber-100 text-amber-700",
  executing: "bg-blue-100 text-blue-700",
  done: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
};

// 单条工具执行记录
function ExecToolRowItem({ row }: { row: ExecRow & { kind: "tool" } }) {
  const [argsText, argsOk] = parseArgs(row.argsRaw);
  return (
    <div className="text-xs font-mono text-gray-600">
      <span className="text-gray-400">[{formatTime(row.startedAt)}]</span>{" "}
      <span className="text-gray-500">{row.stepId}</span>{" "}
      <span className="text-gray-700">{row.toolName}</span>{" "}
      <span
        className={`rounded px-1 ${
          PHASE_STYLE[row.phase] ?? "bg-gray-100 text-gray-600"
        }`}
      >
        {PHASE_LABEL[row.phase] ?? row.phase}
      </span>{" "}
      {row.missingStart && (
        <span className="rounded px-1 bg-orange-100 text-orange-700" title="没等到对应的开始事件,由后续事件合成">
          缺开始事件
        </span>
      )}{" "}
      {row.error && <span className="text-red-600">{row.error}</span>}
      {row.argsRaw !== null && (
        <pre className="mt-0.5 ml-6 whitespace-pre-wrap break-all text-[11px] text-gray-500">
          {argsOk ? "args: " + argsText : "args(原始): " + argsText}
        </pre>
      )}
    </div>
  );
}

// turn 分隔标记
function ExecTurnMarkerItem({ row }: { row: ExecRow & { kind: "turn" } }) {
  return (
    <div className="flex items-center gap-2 py-0.5 text-[11px] text-gray-400">
      <span className="flex-1 border-t border-gray-200" />
      <span>第 {row.index + 1} 轮结束 · {row.stepId}</span>
      <span className="flex-1 border-t border-gray-200" />
    </div>
  );
}

export default function BottomPanel() {
  const toolCalls = useStudioStore((s) => s.toolCalls);
  const logs = useStudioStore((s) => s.logs);
  const clearLogs = useStudioStore((s) => s.clearLogs);
  const execRows = useStudioStore((s) => s.execRows);
  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState<Tab>("tools");

  const errorCount = logs.filter((l) => l.level === "error").length;
  const execCount = execRows.filter((r) => r.kind === "tool").length;
  const failedExecCount = execRows.filter(
    (r) => r.kind === "tool" && r.phase === "failed"
  ).length;

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
          <button
            onClick={() => {
              setTab("exec");
              setExpanded(true);
            }}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs border-b-2 ${
              expanded && tab === "exec"
                ? "border-blue-500 text-blue-600 font-medium"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            <span>执行</span>
            {execCount > 0 && (
              <span
                className={`rounded-full px-1.5 ${
                  failedExecCount > 0
                    ? "bg-red-100 text-red-700"
                    : "bg-gray-100 text-gray-600"
                }`}
              >
                {execCount}
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
          {tab === "exec" &&
            (execRows.length === 0 ? (
              <div className="text-xs text-gray-400">暂无执行记录(Play 运行时显示工具调用时间线)</div>
            ) : (
              [...execRows]
                .sort((a, b) => a.seq - b.seq)
                .map((row) =>
                  row.kind === "turn" ? (
                    <ExecTurnMarkerItem key={`t${row.seq}`} row={row} />
                  ) : (
                    <ExecToolRowItem key={row.key} row={row} />
                  )
                )
            ))}
        </div>
      )}
    </div>
  );
}
