// studio_frontend/src/api.ts
import type { ChatMessage, ProjectMeta, SettingsField, Spec } from "./types";

const BASE = "/api";

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}

export const api = {
  listProjects: () => fetchJson<ProjectMeta[]>(`${BASE}/projects`),
  createProject: (name: string) =>
    fetchJson<{ id: string; name: string }>(`${BASE}/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  getProject: (id: string) => fetchJson<ProjectMeta>(`${BASE}/projects/${id}`),
  getSpec: (id: string) => fetchJson<Spec>(`${BASE}/projects/${id}/spec`),
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
  getEntryInputs: (id: string) =>
    fetchJson<{ fields: string[] }>(`${BASE}/projects/${id}/entry_inputs`),
  deleteProject: (id: string) =>
    fetchJson<{ status: string }>(`${BASE}/projects/${id}`, { method: "DELETE" }),
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
