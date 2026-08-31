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
}

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
