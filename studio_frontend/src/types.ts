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
