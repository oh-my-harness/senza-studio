// Controlled workflow stop: classify runtime responses into operator-facing
// outcomes. The HTTP response is authoritative; 409/404 are normal states,
// not transport failures.
import { apiErrorInfo, type WorkflowStopResult, type WorkflowStopSupport } from "./api";

export type WorkflowStopOutcome =
  | { kind: "stopped"; result: WorkflowStopResult }
  | { kind: "no-running" }
  | { kind: "uncontrolled" }
  | { kind: "unsupported" }
  | { kind: "missing" }
  | { kind: "failed"; message: string };

// The runtime's exact conflict reasons. Matching a known reason keeps a
// genuinely unknown conflict (or an empty body) an error instead of silently
// reporting "nothing to stop".
const NO_RUNNING_REASON = "no running controlled workflow to stop";
const UNCONTROLLED_REASON = "team is not a controlled workflow team";

export function classifyWorkflowStopError(error: unknown): WorkflowStopOutcome {
  const { status, message } = apiErrorInfo(error);
  if (status === 409) {
    const reason = message.toLowerCase();
    if (reason.includes(NO_RUNNING_REASON)) return { kind: "no-running" };
    if (reason.includes(UNCONTROLLED_REASON)) return { kind: "uncontrolled" };
    return { kind: "failed", message: message || "停止工作流失败：HTTP 409" };
  }
  if (status === 404) {
    // An older runtime without the route answers 404 with no runtime error
    // body; an existing runtime names the project it cannot find.
    return message.includes("unknown project")
      ? { kind: "missing" }
      : { kind: "unsupported" };
  }
  return { kind: "failed", message: message || "停止工作流失败" };
}

/** How the Stop control renders for a probe result; `null` means not probed yet. */
export interface WorkflowStopControl {
  canStop: boolean;
  canRetryProbe: boolean;
  hint: string;
}

const STOP_HINT =
  "终止受控工作流。团队、会话与已有证据保留；不能从原执行点恢复。";

export function workflowStopControl(
  support: WorkflowStopSupport | null
): WorkflowStopControl {
  if (support === "unsupported") {
    return {
      canStop: false,
      canRetryProbe: false,
      hint: "当前 Agent Team Runtime 不支持停止工作流，请升级 Runtime",
    };
  }
  if (support === "unknown") {
    return {
      canStop: true,
      canRetryProbe: true,
      hint: "无法确认 Runtime 是否支持停止工作流（探测失败），可重新检测",
    };
  }
  return { canStop: true, canRetryProbe: false, hint: STOP_HINT };
}

export function workflowStopNotice(outcome: WorkflowStopOutcome): string {
  switch (outcome.kind) {
    case "stopped": {
      const { workflow_id, phase, terminal_reason } = outcome.result;
      const reason = terminal_reason ? ` · ${terminal_reason}` : "";
      return `工作流已终止：${workflow_id}（${phase}）${reason}。团队、会话与已有证据保留；不能从原执行点恢复，请开始新的工作流。`;
    }
    case "no-running":
      return "当前没有运行中的受控工作流，无需停止。";
    case "uncontrolled":
      return "该团队不是受控工作流团队，没有可停止的工作流。";
    case "unsupported":
      return "当前 Agent Team Runtime 不支持停止工作流，请升级 Runtime 后重试。";
    case "missing":
      return "团队已不存在，已刷新团队列表。";
    case "failed":
      return outcome.message;
  }
}

export function isNeutralStopOutcome(outcome: WorkflowStopOutcome): boolean {
  return (
    outcome.kind === "no-running" ||
    outcome.kind === "uncontrolled" ||
    outcome.kind === "missing"
  );
}
