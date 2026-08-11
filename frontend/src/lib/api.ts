import type { ProjectMeta, ExampleProject, SpecDiff, StudioEvent, Message, Spec } from '../types';

const BASE = '/api';

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

// Project ids are now derived from free-form project names (see
// ProjectManager::create_project), not always a UUID — so every place a
// single-segment id/runId is interpolated into a URL must be encoded.
// `path` (file paths) is deliberately NOT encoded here: it can legitimately
// contain `/` for nested files, and the backend route
// `/api/projects/{id}/files/{*path}` is a catch-all that expects that.
const enc = encodeURIComponent;

export const api = {
  createProject: (name: string) =>
    fetchJson<ProjectMeta>(`${BASE}/projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),

  listProjects: () => fetchJson<ProjectMeta[]>(`${BASE}/projects`),

  getProject: (id: string) => fetchJson<ProjectMeta>(`${BASE}/projects/${enc(id)}`),

  deleteProject: (id: string) =>
    fetch(`${BASE}/projects/${enc(id)}`, { method: 'DELETE' }).then((r) => {
      if (!r.ok) throw new Error(`${r.status}: ${r.statusText}`);
    }),

  getSpec: (id: string) => fetchJson<Spec | null>(`${BASE}/projects/${enc(id)}/spec`),

  getPendingDiff: (id: string) => fetchJson<SpecDiff | null>(`${BASE}/projects/${enc(id)}/pending-diff`),

  listFiles: (id: string) => fetchJson<string[]>(`${BASE}/projects/${enc(id)}/files`),

  readFile: (id: string, path: string) =>
    fetch(`${BASE}/projects/${enc(id)}/files/${path}`).then(r => r.text()),

  writeFile: (id: string, path: string, content: string) =>
    fetchJson<void>(`${BASE}/projects/${enc(id)}/files/${path}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }),

  getConversation: (id: string) => fetchJson<Message[]>(`${BASE}/projects/${enc(id)}/conversation`),

  converse: (id: string, message: string) =>
    fetchJson<{ run_id: string; ws_url: string }>(`${BASE}/projects/${enc(id)}/converse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    }),

  generate: (id: string) =>
    fetchJson<{ files: string[] }>(`${BASE}/projects/${enc(id)}/generate`, { method: 'POST' }),

  generateDiff: (id: string, diff: SpecDiff) =>
    fetchJson<{ files: string[] }>(`${BASE}/projects/${enc(id)}/generate-diff`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ diff }),
    }),

  runProject: (id: string, mode: 'studio' | 'standalone') =>
    fetchJson<{ run_id: string; ws_url: string }>(`${BASE}/projects/${enc(id)}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    }),

  listRuns: (id: string) => fetchJson<string[]>(`${BASE}/projects/${enc(id)}/runs`),

  getRunEvents: (id: string, runId: string) =>
    fetchJson<StudioEvent[]>(`${BASE}/projects/${enc(id)}/runs/${enc(runId)}/events`),

  stopRun: (id: string, runId: string) =>
    fetchJson<void>(`${BASE}/projects/${enc(id)}/runs/${enc(runId)}/stop`, { method: 'POST' }),

  listExamples: () => fetchJson<ExampleProject[]>(`${BASE}/examples`),

  createFromExample: (exampleId: string, projectName: string) =>
    fetchJson<{ project_id: string }>(`${BASE}/projects/from-example`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ example_id: exampleId, project_name: projectName }),
    }),
};
