// studio_frontend/src/types.ts

export type StepType = "agent" | "checker" | "tool" | "terminal";
export type DisplayType = "chat" | "status" | "table" | "chart" | "approval_form" | "none";

export interface Step {
  name: string;
  type: StepType;
  prompt_template?: string;
  output_key?: string;
  tool?: string;
  component?: string;
  message?: string;
  ui?: { display: DisplayType; fields?: string[] };
  [key: string]: unknown; // next_on_* edges, _component, etc.
}

export interface Spec {
  stages: Step[];
}

export interface ProjectMeta {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  status: string;
  model: string;
  active_session: string | null;
  sessions: string[];
}

export interface ChatMessage {
  role: "user" | "assistant" | "tool";
  content: string;
  toolName?: string;
  timestamp: number;
}

export type StudioStatus = "idle" | "conversing" | "spec_ready" | "playing";

export interface WsEvent {
  type: string;
  text?: string;
  step_id?: string;
  spec?: Spec;
  [key: string]: unknown;
}

export type StepRunStatus = "running" | "done" | "error";

export interface GameCard {
  stepId: string;
  stepName: string;
  text: string;
  status: StepRunStatus;
  // Inspector 运行态用——play.py 塞进 structured._debug 的调试信息：
  // agent step 是 {prompt, tool_calls_count, usage}，tool step 是
  // {tool, args}，checker/pending 状态没有（undefined）。
  debug?: Record<string, unknown> | null;
  route?: string;
  // GameView 的 table/chart 卡片用——structured.fields，ui.fields 点名的
  // 字段值从这里取。
  fields?: Record<string, unknown> | null;
}

// 必须和 studio_backend/play.py 里的 PENDING_APPROVAL 保持一致——checker
// step 用这个 route_key 表示"还没等到人工审批"。
export const PENDING_APPROVAL_ROUTE_KEY = "__pending_approval__";

// 全局设置表单字段（后端 settings.SETTINGS_SCHEMA 下发，前端只负责渲染，
// 不在前端硬编码字段列表——加一项设置只改后端 schema 即可）。
export interface SettingsField {
  group: string;
  key: string;
  label: string;
  placeholder?: string;
  secret: boolean;
}

// 后端不回传明文密钥，用这个哨兵表示"已设置但没给你看"；原样回传表示
// "没改"（见 studio_backend/settings.py）。
export const SECRET_PLACEHOLDER = "__SENZA_UNCHANGED__";

export type LogLevel = "error" | "info";

export interface LogEntry {
  level: LogLevel;
  message: string;
  timestamp: number;
}

export interface ToolCallEntry {
  content: string;
  toolName?: string;
  timestamp: number;
}

// ---- 执行可观测性 V1(Play 工具执行时间线)-----------------------------

// 一条工具执行记录的生命周期:calling(LLM 已发起调用)→ executing(工具
// 开始执行)→ done / failed。failed 同时覆盖中断:运行失败或用户 Stop 时,
// 还没落终态的 in-flight 记录会被统一标记成 failed(见 store 的
// finalizeInFlightExec)。
export type ExecPhase = "calling" | "executing" | "done" | "failed";

export interface ExecToolRow {
  kind: "tool";
  // 全局递增序号——显示排序用。旧行被裁剪出列表后序号不回退,新行的 seq
  // 一定比所有保留行大,排序永远稳定。
  seq: number;
  // 关联键 `${step_id}:${tool_use_id}`
  key: string;
  stepId: string;
  toolUseId: string;
  toolName: string;
  // tool_call_end 下发的原始 args JSON 字符串;还没收到时为 null
  argsRaw: string | null;
  phase: ExecPhase;
  // 执行结束时的 ok 值;未结束为 null
  ok: boolean | null;
  error: string | null;
  // start 事件缺失/乱序时由后续事件合成的记录——UI 要提示"没等到开始事件"
  missingStart: boolean;
  startedAt: number;
  endedAt: number | null;
}

// turn_end 分隔标记(一轮 LLM 调用结束)
export interface ExecTurnMarker {
  kind: "turn";
  seq: number;
  stepId: string;
  index: number;
  timestamp: number;
}

export type ExecRow = ExecToolRow | ExecTurnMarker;

// Play 执行事件——只有带 step_id 的才算(不带 step_id 的同名事件是对话
// 路径 meta-agent 的工具调用,走 toolCalls 逻辑,别混进执行时间线)。
export const EXEC_EVENT_TYPES: Record<string, true> = {
  tool_call_start: true,
  tool_call_end: true,
  tool_execution_start: true,
  tool_execution_end: true,
  turn_end: true,
};
