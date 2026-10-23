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
  ui?: { display: DisplayType; fields?: string[]; title?: string; choice_labels?: Record<string, string> };
  [key: string]: unknown; // next_on_* edges, _component, etc.
}

export interface Spec {
  stages: Step[];
  /** 顶层 ui 块：导出 Agent 的标题/说明/入口输入文案。见 AgentUiPanel。 */
  ui?: Record<string, unknown>;
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
  // 结构化路由验证失败时的完整诊断（code/detail/raw_output）。只有失败卡片
  // 才有；raw_output 是模型可见输出，用来判断截断、选错 JSON 还是漏 route。
  validation?: Record<string, unknown> | null;
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

// ---- 执行活动(前工具阶段)----------------------------------------------
//
// 一个执行单元(Play 的某个 step,或对话路径的 "chat" 伪 step)在工具调用
// 之外"正在做什么"的统一模型。状态机:
//
//   running ──turn_start──▶ waiting_model ──text_delta──▶ model_responding
//      │                        │  ▲
//      │                        │  └──compaction_end──┐
//      │                        ▼                     │
//      └─────────────────── tool 活动 ◀──compaction_start
//
//   终态: done(step_finished/workflow_done/settled)、error(failed/error 事件
//   或 finalize)。tool 事件期间 activity 保持 "running"(工具阶段由
//   execRows 的 calling/executing 行表达,不重复建模)。
export type ExecActivityPhase =
  | "running"
  | "waiting_model"
  | "model_generating"
  | "model_responding"
  | "compacting"
  | "done"
  | "error";
// 状态机图例见上方注释;model_generating = 已收到首 token(或消息开始),模型正在生成。
export interface ExecActivity {
  // "chat" 是对话路径(meta-agent)的伪 step;Play 路径用真实 step_id
  scope: string;
  phase: ExecActivityPhase;
  // 进入当前状态的时间(前端 Date.now())——只表达 UI 经过时长,不是
  // provider 延迟。
  since: number;
  // 错误信息(phase === "error" 时)
  message: string | null;
}

// 活动事件的 scope key:带 step_id 的归该 step,其余归 "chat"。
export const CHAT_ACTIVITY_SCOPE = "chat";

// Play 执行事件——只有带 step_id 的才算(不带 step_id 的同名事件是对话
// 路径 meta-agent 的工具调用,走 toolCalls 逻辑,别混进执行时间线)。
export const EXEC_EVENT_TYPES: Record<string, true> = {
  tool_call_start: true,
  tool_call_end: true,
  tool_execution_start: true,
  tool_execution_end: true,
  turn_end: true,
  // 活动事件:turn_start/compaction_* 由 Play executor 桥转发(step 级);
  // step_started/step_finished 是引擎级事件,同样驱动 step 活动状态。
  turn_start: true,
  compaction_start: true,
  compaction_end: true,
  step_started: true,
  step_finished: true,
};

export interface AgentTeamProject {
  id: string;
  repo_path?: string | null;
}

export interface AgentTeamTemplate {
  id: string;
  version: string;
  name: string;
  member_ids: string[];
}

export interface AgentTeamSettings {
  models: {
    strong: string;
    main: string;
    cheap: string;
  };
  scout_interval_secs: number;
  base_url: string;
  api_key_set: boolean;
}

export interface AgentTeamAgent {
  id: string;
  status: string;
  phase?: string | null;
  error?: string | null;
  activity?: {
    task?: string | null;
    tools?: string[];
  } | null;
}

export interface AgentTeamMember {
  id: string;
  persona: string;
  role_label: string;
  model: string;
  toolkits: string[];
}

export interface AgentTeamMemberInput {
  id: string;
  persona: string;
  role_label: string;
  model: string;
  toolkits: string[];
}

export interface AgentTeamPendingMessage {
  from?: string;
  to: string;
  type?: string;
  body?: string;
}

export interface AgentTeamPulse {
  agents: AgentTeamAgent[];
  pending: AgentTeamPendingMessage[];
  timers: { pending: number };
  issues: { pending: number; confirmed: number };
}

export interface AgentTeamRecoveryFailure {
  team_id: string;
  reason: string;
  detail: string;
}

export interface AgentTeamStartupRecovery {
  status: string;
  persisted_teams: number;
  restored_teams: number;
  failed_teams: AgentTeamRecoveryFailure[];
}
// ---- 平台执行控制台(append-only)----------------------------------------
//
// 元 agent/平台 prompt 的终端式时间线。每条到达前端的事件按顺序映射成
// 一行,只追加不回写(区别于 execRows 的"一条工具记录原地更新"模型)。
export type ConsoleCategory =
  | "PROMPT"
  | "AGENT"
  | "TURN"
  | "MODEL"
  | "TOOL"
  | "SAVE"
  | "COMPACT"
  | "SPEC"
  | "ERROR"
  | "SYS";

export interface ConsoleRow {
  // 全局递增序号——展示排序用,裁剪不回退
  seq: number;
  // 前端收到事件的时间
  timestamp: number;
  category: ConsoleCategory;
  // 单行摘要(不含换行)
  text: string;
  // 可展开的完整内容(args JSON / 工具结果全文 / 错误详情);null = 无
  detail: string | null;
  // 与 start 事件可靠关联出的耗时(ms);关联不上为 null
  durationMs: number | null;
  // 错误行——UI 高亮
  isError: boolean;
  // start/end 配对键:工具用 `${tool_use_id}`,模型响应用 `${message_id}`,
  // savepoint/turn 无配对。
  corrKey?: string;
}

export const CONSOLE_MAX_ROWS = 500;
