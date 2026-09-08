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
  getEntryInputs: (id: string) =>
    fetchJson<{ fields: string[] }>(`${BASE}/projects/${id}/entry_inputs`),
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
