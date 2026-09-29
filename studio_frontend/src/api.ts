// studio_frontend/src/api.ts
import type {
  AgentTeamPulse,
  AgentTeamProject,
  AgentTeamSettings,
  AgentTeamStartupRecovery,
  AgentTeamTemplate,
  AgentTeamMember,
  AgentTeamMemberInput,
  ChatMessage,
  ProjectMeta,
  SettingsField,
  Spec,
} from "./types";
import type { AgentTeamEvent } from "./agentTeamEvents";
import type { AgentInfo } from "./player/types";

const BASE = "/api";
const bootstrapToken = import.meta.env.DEV
  ? import.meta.env.VITE_SENZA_STUDIO_API_TOKEN
  : undefined;
let authenticationReady: Promise<void> | null = null;

export function initializeAuthentication(): Promise<void> {
  if (!bootstrapToken) return Promise.resolve();
  authenticationReady ??= fetch("/auth/bootstrap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: bootstrapToken }),
  }).then((response) => {
    if (!response.ok) throw new Error(`authentication failed: ${response.status}`);
  });
  return authenticationReady;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  await initializeAuthentication();
  const r = await fetch(url, { ...init, credentials: "same-origin" });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}

export const api = {
  listAgentTeams: () =>
    fetchJson<{ projects: AgentTeamProject[] }>(`${BASE}/team/projects`),
  createAgentTeam: (input: {
    id: string;
    name?: string;
    template_id?: string;
    repo_path?: string;
  }) =>
    fetchJson<{ ok: boolean }>(`${BASE}/team/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  restartAgentTeam: (id: string) =>
    fetchJson<{ ok: boolean }>(
      `${BASE}/team/projects/restart?id=${encodeURIComponent(id)}`,
      { method: "POST" }
    ),
  abortAgentTeam: (project: string, agent: string) =>
    fetchJson<{ ok: boolean; interrupted?: string[] }>(
      `${BASE}/team/agent/abort?project=${encodeURIComponent(
        project
      )}&agent=${encodeURIComponent(agent)}`,
      { method: "POST" }
    ),
  deleteAgentTeam: (id: string) =>
    fetchJson<{ ok: boolean }>(
      `${BASE}/team/projects?id=${encodeURIComponent(id)}`,
      { method: "DELETE" }
    ),
  getAgentTeamPulse: (id: string) =>
    fetchJson<AgentTeamPulse>(
      `${BASE}/team/pulse?project=${encodeURIComponent(id)}`
    ),
  listAgentTeamMembers: (project: string) =>
    fetchJson<{ members: AgentTeamMember[] }>(
      `${BASE}/team/members?project=${encodeURIComponent(project)}`
    ),
  addAgentTeamMember: (project: string, input: AgentTeamMemberInput) =>
    fetchJson<{ ok: boolean }>(`${BASE}/team/members`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project, ...input }),
    }),
  updateAgentTeamMember: (
    project: string,
    id: string,
    input: Omit<AgentTeamMemberInput, "id">
  ) =>
    fetchJson<{ ok: boolean; rebuilt: boolean }>(`${BASE}/team/agent/config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project, agent: id, ...input }),
    }),
  deleteAgentTeamMember: (project: string, id: string) =>
    fetchJson<{ ok: boolean }>(
      `${BASE}/team/members?project=${encodeURIComponent(
        project
      )}&agent=${encodeURIComponent(id)}`,
      { method: "DELETE" }
    ),
  sendAgentTeamMessage: (project: string, target: string, text: string) =>
    fetchJson<{ ok: boolean }>(`${BASE}/team/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project, target, text }),
    }),
  getAgentTeamChatHistory: (
    project: string,
    agent: string,
    limit = 50,
    before?: number
  ) =>
    fetchJson<{ messages: AgentTeamEvent[] }>(
      `${BASE}/team/chat?project=${encodeURIComponent(project)}&agent=${encodeURIComponent(
        agent
      )}&limit=${limit}${typeof before === "number" ? `&before=${before}` : ""}`
    ),
  listAgentTeamTemplates: () =>
    fetchJson<{ templates: AgentTeamTemplate[] }>(`${BASE}/team/templates`),
  getAgentTeamStartup: () =>
    fetchJson<{ recovery: AgentTeamStartupRecovery }>(`${BASE}/team/startup`),
  getAgentTeamSettings: () =>
    fetchJson<AgentTeamSettings>(`${BASE}/team/settings`),
  updateAgentTeamSettings: (input: {
    strong: string;
    main: string;
    cheap: string;
    scout_interval_secs: number;
    base_url: string;
    api_key?: string;
  }) =>
    fetchJson<{ ok: boolean; note: string }>(`${BASE}/team/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  listProjects: () => fetchJson<ProjectMeta[]>(`${BASE}/projects`),
  createProject: (name: string) =>
    fetchJson<{ id: string; name: string }>(`${BASE}/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  getProject: (id: string) => fetchJson<ProjectMeta>(`${BASE}/projects/${id}`),
  getSpec: (id: string) => fetchJson<Spec>(`${BASE}/projects/${id}/spec`),
  // 展开能力组件之后的 spec——画布画 group 用。展开失败不是 HTTP 错误，
  // 原因在 error 字段里（编辑到一半的 spec 展不开是常态）。
  getExpandedSpec: (id: string) =>
    fetchJson<{ spec: Spec | null; error: string | null }>(
      `${BASE}/projects/${id}/expanded_spec`,
    ),
  getMessages: (id: string) =>
    fetchJson<ChatMessage[]>(`${BASE}/projects/${id}/messages`),
  updateSpec: (id: string, spec: Spec) =>
    fetchJson<{ status: string }>(`${BASE}/projects/${id}/spec`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec }),
    }),
  createSession: (id: string) =>
    fetchJson<{ session_id: string }>(`${BASE}/projects/${id}/sessions`, {
      method: "POST",
    }),
  listSessions: (id: string) =>
    fetchJson<{ sessions: string[]; active: string | null }>(
      `${BASE}/projects/${id}/sessions`
    ),
  deleteProject: (id: string) =>
    fetchJson<{ status: string }>(`${BASE}/projects/${id}`, { method: "DELETE" }),
  // 上传文档：multipart，不走 fetchJson（它写死了 JSON body）。不设
  // Content-Type，让浏览器自己带上 multipart 的 boundary。
  uploadDocument: async (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const r = await fetch(`${BASE}/projects/${id}/documents`, {
      method: "POST",
      body: form,
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail || `${r.status}`);
    return body as {
      name: string;
      kind: string;
      summary: string;
      ok: boolean;
    };
  },
  // Game view 的渲染契约。和导出 Agent 的 GET /api/agent 同构，由后端同一个
  // describe_agent 生成——Game view 就是那个界面的预览。
  getAgent: (id: string) => fetchJson<AgentInfo>(`${BASE}/projects/${id}/agent`),
  // 导出成可独立运行的项目目录。spec 不合法 / 组件展不开时后端返回 400，
  // detail 里是能直接给用户看的原因。
  exportProject: (id: string, name?: string) =>
    fetchJson<{
      path: string;
      with_webui: boolean;
      note: string | null;
    }>(`${BASE}/projects/${id}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name ?? null }),
    }),
  getSettings: () =>
    fetchJson<{
      schema: SettingsField[];
      sections: Record<string, string>;
      values: Record<string, string>;
      // 被环境变量接管的项——面板据此置灰。密钥字段的值是哨兵。
      env_overrides: Record<string, string>;
    }>(`${BASE}/settings`),
  updateSettings: (values: Record<string, string>) =>
    fetchJson<{
      status: string;
      values: Record<string, string>;
      env_overrides: Record<string, string>;
    }>(`${BASE}/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    }),
};

export function createWebSocket(projectId: string): WebSocket {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return new WebSocket(`${proto}//${location.host}/ws/projects/${projectId}`);
}
