// studio_frontend/src/components/BottomPanel.tsx
import { useState, useEffect, useRef } from "react";
import { useStudioStore } from "../store";
import { formatElapsed } from "../utils";
import type {
  ExecRow,
  ExecActivity,
  ExecActivityPhase,
  ConsoleRow,
} from "../types";

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

// 活动状态的中文标签 + 颜色。done/error 是终态,保留显示;running 系列
// 表示"工具之间的执行期"。
const ACTIVITY_LABEL: Record<ExecActivityPhase, string> = {
  running: "运行中",
  waiting_model: "等待模型响应",
  model_generating: "模型生成中",
  model_responding: "模型响应中",
  compacting: "正在压缩上下文",
  done: "已完成",
  error: "出错",
};

const ACTIVITY_STYLE: Record<ExecActivityPhase, string> = {
  running: "bg-blue-100 text-blue-700",
  waiting_model: "bg-amber-100 text-amber-700",
  model_generating: "bg-sky-100 text-sky-700",
  model_responding: "bg-blue-100 text-blue-700",
  compacting: "bg-purple-100 text-purple-700",
  done: "bg-green-100 text-green-700",
  error: "bg-red-100 text-red-700",
};
// 控制台类目标签色——开发者终端感:分类标签用固定宽度等宽,错误红。
const CATEGORY_STYLE: Record<string, string> = {
  PROMPT: "text-emerald-600",
  AGENT: "text-indigo-600",
  TURN: "text-sky-600",
  MODEL: "text-blue-600",
  TOOL: "text-amber-600",
  SAVE: "text-gray-400",
  COMPACT: "text-purple-600",
  SPEC: "text-cyan-600",
  ERROR: "text-red-600 font-medium",
  SYS: "text-gray-500",
};

// 当前活动行——显示一个执行单元(Play step 或 "chat")此刻在做什么。
// 前端经过时长(since -> now)用 1s 间隔的定时器驱动,只表达 UI 等待时长,
// 不是 provider 延迟。终态(done/error)不再计时,定格在进入终态的时长。
export function ExecActivityRow({ scope, activity }: { scope: string; activity: ExecActivity }) {
  const [now, setNow] = useState(Date.now());
  const active = activity.phase !== "done" && activity.phase !== "error";
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  const elapsedMs = Math.max(0, now - activity.since);
  const elapsed = formatElapsed(elapsedMs);
  return (
    <div className="flex items-center gap-2 text-xs" data-testid={`exec-activity-${scope}`}>
      {active && (
        <span className="inline-block h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
      )}
      <span className="font-mono text-gray-700">{scope}</span>
      <span
        className={`rounded px-1.5 py-0.5 ${ACTIVITY_STYLE[activity.phase]}`}
      >
        {ACTIVITY_LABEL[activity.phase]}
      </span>
      {active && <span className="text-gray-400">{elapsed}</span>}
      {activity.message && (
        <span className="text-red-500 truncate max-w-[50%]" title={activity.message}>
          {activity.message}
        </span>
      )}
    </div>
  );
}

// 控制台单行:时间戳 | 类目标签 | 摘要 (+可选耗时/可展开详情)。
// detail 非空时整行可点击展开/收起;错误行红字;耗时右对齐灰字。
function ConsoleRowItem({ row }: { row: ConsoleRow }) {
  const [open, setOpen] = useState(false);
  const hasDetail = row.detail !== null && row.detail.length > 0;
  return (
    <div className="font-mono text-[11px] leading-5">
      <div
        className={`flex items-baseline gap-2 ${row.isError ? "bg-red-950/60" : ""}`}
        data-testid={`console-row-${row.seq}`}
      >
        <span className="shrink-0 text-gray-500">{formatTime(row.timestamp)}</span>
        <span
          className={`w-[52px] shrink-0 font-medium ${
            CATEGORY_STYLE[row.category] ?? "text-gray-500"
          }`}
        >
          {row.category}
        </span>
        <span
          className={`flex-1 truncate ${row.isError ? "text-red-400" : "text-gray-200"}`}
          title={row.text}
        >
          {row.text}
        </span>
        {row.durationMs !== null && (
          <span className="shrink-0 text-gray-500">{(row.durationMs / 1000).toFixed(1)}s</span>
        )}
        {hasDetail && (
          <button
            onClick={() => setOpen((v) => !v)}
            className="shrink-0 text-gray-600 hover:text-gray-300"
          >
            {open ? "▾" : "▸"}
          </button>
        )}
      </div>
      {hasDetail && open && (
        <pre className="ml-[72px] mr-2 max-h-40 overflow-y-auto whitespace-pre-wrap break-all rounded bg-gray-900 px-2 py-1 text-[10px] text-gray-400">
          {row.detail}
        </pre>
      )}
    </div>
  );
}

// 控制台容器:append-only 行列表 + "贴底才自动滚动"的滚动策略。
// 用户向上翻就不再强制跟底;重新滚到底部附近后恢复跟随。
function ConsolePane({ rows }: { rows: ConsoleRow[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const nearBottomRef = useRef(true);
  const lastCountRef = useRef(rows.length);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (rows.length > lastCountRef.current && nearBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
    lastCountRef.current = rows.length;
  }, [rows.length]);
  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    nearBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };
  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className="max-h-64 overflow-y-auto rounded border border-gray-200 bg-gray-950 px-2 py-1.5 font-mono text-gray-300"
      data-testid="console-pane"
    >
      {rows.length === 0 ? (
        <div className="text-[11px] text-gray-500">
          控制台空闲——发送一条 prompt 后这里显示处理过程
        </div>
      ) : (
        [...rows]
          .sort((a, b) => a.seq - b.seq)
          .map((row) => <ConsoleRowItem key={row.seq} row={row} />)
      )}
    </div>
  );
}

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
  const execActivity = useStudioStore((s) => s.execActivity);
  const consoleRows = useStudioStore((s) => s.consoleRows);
  const [tab, setTab] = useState<Tab>("tools");

  const errorCount = logs.filter((l) => l.level === "error").length;
  const execCount = execRows.filter((r) => r.kind === "tool").length;
  const failedExecCount = execRows.filter(
    (r) => r.kind === "tool" && r.phase === "failed"
  ).length;

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-white">
      <div className="w-full flex items-center justify-between px-2">
        <div className="flex items-center">
          <button
            onClick={() => {
              setTab("tools");
            }}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs border-b-2 ${
              tab === "tools"
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
            }}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs border-b-2 ${
              tab === "logs"
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
            }}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs border-b-2 ${
              tab === "exec"
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
          {tab === "logs" && logs.length > 0 && (
            <button
              onClick={clearLogs}
              className="text-xs text-gray-400 hover:text-gray-700"
            >
              清空
            </button>
          )}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-auto border-t border-gray-100 px-4 py-2 space-y-1">
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
          {tab === "exec" && (
            <>
              {Object.keys(execActivity).length > 0 && (
                <div className="space-y-1 rounded border border-gray-100 bg-gray-50 px-2 py-1.5">
                  {Object.entries(execActivity)
                    .sort(([a], [b]) => (a === "chat" ? -1 : b === "chat" ? 1 : a.localeCompare(b)))
                    .map(([scope, activity]) => (
                      <ExecActivityRow key={scope} scope={scope} activity={activity} />
                    ))}
                </div>
              )}
              {/* 平台执行控制台——活动行下方,append-only 时间线 */}
              <ConsolePane rows={consoleRows} />
              {execRows.length === 0 ? (
                <div className="text-xs text-gray-400">
                  {Object.keys(execActivity).length > 0
                    ? "当前活动如上(工具调用时间线在事件到达后显示)"
                    : "暂无执行记录(Play 运行时显示工具调用时间线)"}
                </div>
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
              )}
            </>
          )}
      </div>
    </div>
  );
}
