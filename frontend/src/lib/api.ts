import type { ProjectMeta, ExampleProject, SpecDiff, StudioEvent, Message, Spec } from '../types';

const BASE = '/api';

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export const api = {
  createProject: (name: string) =>
    fetchJson<ProjectMeta>(`${BASE}/projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),

  listProjects: () => fetchJson<ProjectMeta[]>(`${BASE}/projects`),

  getProject: (id: string) => fetchJson<ProjectMeta>(`${BASE}/projects/${id}`),

  deleteProject: (id: string) =>
    fetch(`${BASE}/projects/${id}`, { method: 'DELETE' }).then((r) => {
      if (!r.ok) throw new Error(`${r.status}: ${r.statusText}`);
    }),

  getSpec: (id: string) => fetchJson<Spec | null>(`${BASE}/projects/${id}/spec`),

  listFiles: (id: string) => fetchJson<string[]>(`${BASE}/projects/${id}/files`),

  readFile: (id: string, path: string) =>
    fetch(`${BASE}/projects/${id}/files/${path}`).then(r => r.text()),

  writeFile: (id: string, path: string, content: string) =>
    fetchJson<void>(`${BASE}/projects/${id}/files/${path}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }),

  getConversation: (id: string) => fetchJson<Message[]>(`${BASE}/projects/${id}/conversation`),

  converse: (id: string, message: string) =>
    fetchJson<{ run_id: string; ws_url: string }>(`${BASE}/projects/${id}/converse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    }),

  generate: (id: string) =>
    fetchJson<{ files: string[] }>(`${BASE}/projects/${id}/generate`, { method: 'POST' }),

  generateDiff: (id: string, diff: SpecDiff) =>
    fetchJson<{ files: string[] }>(`${BASE}/projects/${id}/generate-diff`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ diff }),
    }),

  runProject: (id: string, mode: 'studio' | 'standalone') =>
    fetchJson<{ run_id: string; ws_url: string }>(`${BASE}/projects/${id}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    }),

  listRuns: (id: string) => fetchJson<string[]>(`${BASE}/projects/${id}/runs`),

  getRunEvents: (id: string, runId: string) =>
    fetchJson<StudioEvent[]>(`${BASE}/projects/${id}/runs/${runId}/events`),

  stopRun: (id: string, runId: string) =>
    fetchJson<void>(`${BASE}/projects/${id}/runs/${runId}/stop`, { method: 'POST' }),

  listExamples: () => fetchJson<ExampleProject[]>(`${BASE}/examples`),

  createFromExample: (exampleId: string, projectName: string) =>
    fetchJson<{ project_id: string }>(`${BASE}/projects/from-example`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ example_id: exampleId, project_name: projectName }),
    }),
};
