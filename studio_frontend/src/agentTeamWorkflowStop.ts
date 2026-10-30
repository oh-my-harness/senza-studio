// Controlled workflow stop: classify runtime responses into operator-facing
// outcomes. The HTTP response is authoritative; 409/404 are normal states,
// not transport failures.
import { apiErrorInfo, type WorkflowStopResult } from "./api";

export type WorkflowStopOutcome =
  | { kind: "stopped"; result: WorkflowStopResult }
  | { kind: "no-running" }
  | { kind: "uncontrolled" }
  | { kind: "unsupported" }
  | { kind: "missing" }
  | { kind: "failed"; message: string };

export function classifyWorkflowStopError(error: unknown): WorkflowStopOutcome {
  const { status, message } = apiErrorInfo(error);
  if (status === 409) {
    return message.includes("not a controlled workflow")
      ? { kind: "uncontrolled" }
      : { kind: "no-running" };
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
