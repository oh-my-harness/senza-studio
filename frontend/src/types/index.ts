export interface ProjectMeta {
  id: string;
  name: string;
  dir: string;
  created_at: string;
}

export type AgentType = 'single' | 'single_with_tools' | 'linear_workflow' | 'conditional_workflow';
export type DeployMode = 'cli' | 'api';

export interface ToolSpec {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  implementation: string;
}

export interface WorkflowStep {
  id: string;
  name: string;
  prompt: string;
  allowed_tools: string[];
}

export interface EdgeConditionSpec {
  op: string;
  pointer: string;
  value?: unknown;
}

export interface WorkflowEdge {
  from: string;
  to: string;
  condition?: EdgeConditionSpec;
}

export interface JudgeSpec {
  strategy: string;
}

export interface WorkflowSpec {
  entry_step: string;
  steps: WorkflowStep[];
  edges: WorkflowEdge[];
  judge: JudgeSpec;
}

export interface Spec {
  agent_type: AgentType;
  name: string;
  description: string;
  model: string;
  system_prompt: string;
  max_tokens: number;
  budget?: { max_cost: number };
  tools: ToolSpec[];
  workflow?: WorkflowSpec;
  deploy: DeployMode;
  provider: { type: string; base_url?: string };
}

export interface SpecDiffOp {
  op: string;
  path: string;
  value?: unknown;
}

export interface SpecDiff {
  ops: SpecDiffOp[];
}

export interface ExampleProject {
  id: string;
  name: string;
  description: string;
  tags: string[];
  files: { path: string; content: string }[];
}

export interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: string;
}

export interface StudioEvent {
  type: string;
  [key: string]: unknown;
}

export interface StepState {
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped';
  output?: string;
  structured?: unknown;
}

export interface RunSummary {
  run_id: string;
  status: string;
  started_at: string;
  ended_at?: string;
}

export type RunStatus = 'idle' | 'running' | 'completed' | 'failed' | 'waiting_input';
export type RunView = 'chat' | 'execution';
export type ConversationStatus = 'idle' | 'streaming' | 'emitting_spec';
