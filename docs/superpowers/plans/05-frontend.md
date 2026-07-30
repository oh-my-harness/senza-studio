# Plan 5: React Frontend

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the React frontend with 5 tabs (Converse, Run, Code, DAG, Trace), split run views (chat vs execution), Zustand store, and WebSocket client.

**Architecture:** React + Vite + Tailwind + shadcn/ui. Zustand for per-project state. WebSocket for real-time streaming (converse + run). React Flow for DAG visualization. Code editor via Monaco or CodeMirror.

**Tech Stack:** React 19, Vite, Tailwind CSS, shadcn/ui, Zustand, @xyflow/react, @monaco-editor/react, lucide-react.

## Global Constraints

(See `00-overview.md`)

---

## File Structure

```
frontend/
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── tsconfig.json
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── index.css
│   ├── store/
│   │   └── projectStore.ts       # Zustand store
│   ├── lib/
│   │   ├── api.ts                # REST API client
│   │   └── ws.ts                 # WebSocket client
│   ├── types/
│   │   └── index.ts              # TypeScript types
│   ├── components/
│   │   ├── layout/
│   │   │   ├── TopBar.tsx
│   │   │   ├── FileTree.tsx
│   │   │   ├── StatusBar.tsx
│   │   │   └── RightPanel.tsx
│   │   ├── converse/
│   │   │   └── ConverseTab.tsx
│   │   ├── run/
│   │   │   ├── RunTab.tsx        # Dispatcher: chat vs execution
│   │   │   ├── ChatView.tsx      # Single agent chat
│   │   │   └── ExecutionView.tsx # Workflow execution + inline DAG
│   │   ├── code/
│   │   │   └── CodeTab.tsx
│   │   ├── dag/
│   │   │   └── DagTab.tsx        # Full-screen DAG (React Flow)
│   │   ├── trace/
│   │   │   └── TraceTab.tsx
│   │   └── examples/
│   │       └── ExamplePicker.tsx
│   └── hooks/
│       ├── useConverseWs.ts
│       └── useRunWs.ts
```

---

### Task 1: Scaffold Vite + React + Tailwind + shadcn/ui

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/index.css`

- [ ] **Step 1: Initialize Vite project**

```bash
cd frontend
npm create vite@latest . -- --template react-ts
```

- [ ] **Step 2: Install dependencies**

```bash
npm install zustand @xyflow/react lucide-react
npm install -D tailwindcss @tailwindcss/vite
npx shadcn@latest init
```

- [ ] **Step 3: Configure Tailwind**

`frontend/src/index.css`:
```css
@import "tailwindcss";
```

`frontend/vite.config.ts`:
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:3000',
      '/ws': {
        target: 'ws://localhost:3000',
        ws: true,
      },
    },
  },
})
```

- [ ] **Step 4: Create App.tsx skeleton**

```tsx
function App() {
  return (
    <div className="h-screen flex flex-col">
      <div className="border-b px-4 py-2">TopBar</div>
      <div className="flex-1 flex">
        <div className="w-48 border-r">FileTree</div>
        <div className="flex-1 flex flex-col">
          <div className="flex border-b">
            <button className="px-4 py-2">对话</button>
            <button className="px-4 py-2">运行</button>
            <button className="px-4 py-2">代码</button>
            <button className="px-4 py-2">DAG</button>
            <button className="px-4 py-2">Trace</button>
          </div>
          <div className="flex-1">Main Panel</div>
        </div>
        <div className="w-72 border-l">Right Panel</div>
      </div>
      <div className="border-t px-4 py-1 text-sm">Status</div>
    </div>
  )
}

export default App
```

- [ ] **Step 5: Verify dev server**

```bash
npm run dev
```
Expected: Vite dev server running on port 5173.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: scaffold React + Vite + Tailwind frontend"
```

---

### Task 2: TypeScript Types (types/index.ts)

**Files:**
- Create: `frontend/src/types/index.ts`

- [ ] **Step 1: Write types**

```typescript
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
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "feat: add TypeScript types"
```

---

### Task 3: REST API Client (lib/api.ts)

**Files:**
- Create: `frontend/src/lib/api.ts`

- [ ] **Step 1: Implement API client**

```typescript
import type { ProjectMeta, ExampleProject, Spec, SpecDiff, StudioEvent } from '../types';

const BASE = '/api';

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export const api = {
  // Projects
  createProject: (name: string) =>
    fetchJson<ProjectMeta>(`${BASE}/projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),

  listProjects: () => fetchJson<ProjectMeta[]>(`${BASE}/projects`),

  getProject: (id: string) => fetchJson<ProjectMeta>(`${BASE}/projects/${id}`),

  listFiles: (id: string) => fetchJson<string[]>(`${BASE}/projects/${id}/files`),

  readFile: (id: string, path: string) =>
    fetch(`${BASE}/projects/${id}/files/${path}`).then(r => r.text()),

  writeFile: (id: string, path: string, content: string) =>
    fetchJson<void>(`${BASE}/projects/${id}/files/${path}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }),

  // Converse
  converse: (id: string, message: string) =>
    fetchJson<{ run_id: string; ws_url: string }>(`${BASE}/projects/${id}/converse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    }),

  // Generate
  generate: (id: string) =>
    fetchJson<{ files: string[] }>(`${BASE}/projects/${id}/generate`, { method: 'POST' }),

  generateDiff: (id: string, diff: SpecDiff) =>
    fetchJson<{ files: string[] }>(`${BASE}/projects/${id}/generate-diff`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ diff }),
    }),

  // Run
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

  // Examples
  listExamples: () => fetchJson<ExampleProject[]>(`${BASE}/examples`),

  createFromExample: (exampleId: string, projectName: string) =>
    fetchJson<{ project_id: string }>(`${BASE}/projects/from-example`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ example_id: exampleId, project_name: projectName }),
    }),
};
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "feat: add REST API client"
```

---

### Task 4: Zustand Store (store/projectStore.ts)

**Files:**
- Create: `frontend/src/store/projectStore.ts`

**Design doc reference:** §5 前端状态管理

- [ ] **Step 1: Implement store**

```typescript
import { create } from 'zustand';
import type {
  ProjectMeta, Spec, SpecDiff, Message, StudioEvent, StepState,
  RunStatus, RunView, ConversationStatus, RunSummary,
} from '../types';
import { api } from '../lib/api';

interface ProjectStore {
  // Project
  project: ProjectMeta | null;
  setProject: (p: ProjectMeta) => void;

  // Files
  files: Record<string, string>;
  dirtyFiles: Set<string>;
  loadFiles: () => Promise<void>;
  saveFile: (path: string, content: string) => Promise<void>;

  // Conversation
  conversation: Message[];
  conversationStatus: ConversationStatus;
  currentSpec: Spec | null;
  sendMessage: (text: string) => void;
  addConversationMessage: (msg: Message) => void;
  setConversationStatus: (s: ConversationStatus) => void;
  setCurrentSpec: (s: Spec | null) => void;

  // Run
  runs: RunSummary[];
  activeRunId: string | null;
  runStatus: RunStatus;
  runView: RunView;
  runMessages: Message[];
  liveEvents: StudioEvent[];
  stepStates: Record<string, StepState>;
  activeStepId: string | null;

  startRun: (mode: 'studio' | 'standalone') => Promise<void>;
  sendRunMessage: (text: string) => void;
  submitTask: (text: string) => void;
  stopRun: () => Promise<void>;
  addRunEvent: (event: StudioEvent) => void;
  setRunStatus: (s: RunStatus) => void;

  // Generate
  generate: () => Promise<void>;
  applySpecDiff: (diff: SpecDiff) => Promise<void>;

  // Events from WebSocket
  onConverseEvent: (event: StudioEvent) => void;
  onRunEvent: (event: StudioEvent) => void;

  // Active tab
  activeTab: 'converse' | 'run' | 'code' | 'dag' | 'trace';
  setActiveTab: (t: 'converse' | 'run' | 'code' | 'dag' | 'trace') => void;
}

export const useProjectStore = create<ProjectStore>((set, get) => ({
  project: null,
  setProject: (p) => set({ project: p }),

  files: {},
  dirtyFiles: new Set(),
  loadFiles: async () => {
    const project = get().project;
    if (!project) return;
    const fileList = await api.listFiles(project.id);
    const files: Record<string, string> = {};
    for (const path of fileList) {
      files[path] = await api.readFile(project.id, path);
    }
    set({ files });
  },
  saveFile: async (path, content) => {
    const project = get().project;
    if (!project) return;
    await api.writeFile(project.id, path, content);
    set((state) => {
      const files = { ...state.files, [path]: content };
      const dirtyFiles = new Set(state.dirtyFiles);
      dirtyFiles.delete(path);
      return { files, dirtyFiles };
    });
  },

  conversation: [],
  conversationStatus: 'idle',
  currentSpec: null,
  sendMessage: (text) => {
    get().addConversationMessage({ role: 'user', content: text });
    set({ conversationStatus: 'streaming' });
    // WebSocket sends the message — handled by useConverseWs hook
  },
  addConversationMessage: (msg) =>
    set((s) => ({ conversation: [...s.conversation, msg] })),
  setConversationStatus: (s) => set({ conversationStatus: s }),
  setCurrentSpec: (s) => set({ currentSpec: s }),

  runs: [],
  activeRunId: null,
  runStatus: 'idle',
  runView: 'chat',
  runMessages: [],
  liveEvents: [],
  stepStates: {},
  activeStepId: null,

  startRun: async (mode) => {
    const project = get().project;
    if (!project) return;
    const spec = get().currentSpec;
    const runView: RunView = spec?.agent_type?.includes('workflow') ? 'execution' : 'chat';
    const res = await api.runProject(project.id, mode);
    set({
      activeRunId: res.run_id,
      runStatus: 'running',
      runView,
      runMessages: [],
      liveEvents: [],
      stepStates: {},
      activeStepId: null,
    });
  },
  sendRunMessage: (text) => {
    // WebSocket sends the message — handled by useRunWs hook
    set((s) => ({
      runMessages: [...s.runMessages, { role: 'user', content: text }],
    }));
  },
  submitTask: (text) => {
    // Same as sendRunMessage but for workflow execution view
    set((s) => ({
      runMessages: [...s.runMessages, { role: 'user', content: text }],
    }));
  },
  stopRun: async () => {
    const project = get().project;
    const runId = get().activeRunId;
    if (!project || !runId) return;
    await api.stopRun(project.id, runId);
    set({ runStatus: 'idle' });
  },
  addRunEvent: (event) =>
    set((s) => ({ liveEvents: [...s.liveEvents, event] })),
  setRunStatus: (s) => set({ runStatus: s }),

  generate: async () => {
    const project = get().project;
    if (!project) return;
    await api.generate(project.id);
    await get().loadFiles();
  },
  applySpecDiff: async (diff) => {
    const project = get().project;
    if (!project) return;
    await api.generateDiff(project.id, diff);
    await get().loadFiles();
  },

  onConverseEvent: (event) => {
    const type = event.type;
    if (type === 'text_delta') {
      const text = (event as any).text || '';
      set((s) => {
        const conv = [...s.conversation];
        const last = conv[conv.length - 1];
        if (last && last.role === 'assistant') {
          conv[conv.length - 1] = { ...last, content: last.content + text };
        } else {
          conv.push({ role: 'assistant', content: text });
        }
        return { conversation: conv };
      });
    } else if (type === 'settled') {
      set({ conversationStatus: 'idle' });
    } else if (type === 'tool_call_start' && (event as any).tool_name === 'emit_spec') {
      set({ conversationStatus: 'emitting_spec' });
    }
  },

  onRunEvent: (event) => {
    get().addRunEvent(event);
    const type = event.type;

    if (type === 'text_delta') {
      const text = (event as any).text || '';
      set((s) => {
        const msgs = [...s.runMessages];
        const last = msgs[msgs.length - 1];
        if (last && last.role === 'assistant') {
          msgs[msgs.length - 1] = { ...last, content: last.content + text };
        } else {
          msgs.push({ role: 'assistant', content: text });
        }
        return { runMessages: msgs };
      });
    } else if (type === 'input_request') {
      set({ runStatus: 'waiting_input' });
    } else if (type === 'settled') {
      set({ runStatus: 'running' }); // still running, waiting for next input
    } else if (type === 'error') {
      set({ runStatus: 'failed' });
    } else if (type === 'step_started') {
      const stepId = (event as any).step_id;
      set((s) => ({
        activeStepId: stepId,
        stepStates: {
          ...s.stepStates,
          [stepId]: { ...s.stepStates[stepId], status: 'running' },
        },
      }));
    } else if (type === 'step_finished') {
      const stepId = (event as any).step_id;
      const result = (event as any).result || {};
      set((s) => ({
        stepStates: {
          ...s.stepStates,
          [stepId]: {
            status: 'done',
            output: result.output,
            structured: result.structured,
          },
        },
      }));
    } else if (type === 'paused') {
      set({ runStatus: 'waiting_input' });
    } else if (type === 'failed' || type === 'cancelled') {
      set({ runStatus: 'failed' });
    }
  },

  activeTab: 'converse',
  setActiveTab: (t) => set({ activeTab: t }),
}));
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "feat: add Zustand project store"
```

---

### Task 5: WebSocket Client + Hooks

**Files:**
- Create: `frontend/src/lib/ws.ts`
- Create: `frontend/src/hooks/useConverseWs.ts`
- Create: `frontend/src/hooks/useRunWs.ts`

- [ ] **Step 1: Implement ws.ts**

```typescript
import type { StudioEvent } from '../types';

export class WsClient {
  private ws: WebSocket | null = null;
  private onEvent: (event: StudioEvent) => void;
  private onSend: (text: string) => void;

  constructor(url: string, onEvent: (event: StudioEvent) => void, onSend: (text: string) => void) {
    this.onEvent = onEvent;
    this.onSend = onSend;
    this.ws = new WebSocket(url);
    this.ws.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data);
        this.onEvent(event);
      } catch {
        // ignore non-JSON messages
      }
    };
  }

  send(text: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(text);
    }
  }

  sendJson(data: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  close() {
    this.ws?.close();
    this.ws = null;
  }
}
```

- [ ] **Step 2: Implement hooks**

```typescript
// hooks/useConverseWs.ts
import { useEffect, useRef } from 'react';
import { useProjectStore } from '../store/projectStore';
import { WsClient } from '../lib/ws';

export function useConverseWs() {
  const project = useProjectStore((s) => s.project);
  const onConverseEvent = useProjectStore((s) => s.onConverseEvent);
  const wsRef = useRef<WsClient | null>(null);

  useEffect(() => {
    if (!project) return;
    const ws = new WsClient(
      `ws://${location.host}/ws/converse/${project.id}`,
      onConverseEvent,
      () => {},
    );
    wsRef.current = ws;
    return () => ws.close();
  }, [project, onConverseEvent]);

  return {
    send: (text: string) => wsRef.current?.send(text),
  };
}
```

```typescript
// hooks/useRunWs.ts
import { useEffect, useRef } from 'react';
import { useProjectStore } from '../store/projectStore';
import { WsClient } from '../lib/ws';

export function useRunWs() {
  const project = useProjectStore((s) => s.project);
  const activeRunId = useProjectStore((s) => s.activeRunId);
  const onRunEvent = useProjectStore((s) => s.onRunEvent);
  const wsRef = useRef<WsClient | null>(null);

  useEffect(() => {
    if (!project || !activeRunId) return;
    const ws = new WsClient(
      `ws://${location.host}/ws/run/${project.id}`,
      onRunEvent,
      () => {},
    );
    wsRef.current = ws;
    return () => ws.close();
  }, [project, activeRunId, onRunEvent]);

  return {
    sendInput: (text: string) => {
      if (activeRunId) {
        wsRef.current?.sendJson({ run_id: activeRunId, input: text });
      }
    },
  };
}
```

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: add WebSocket client and hooks"
```

---

### Task 6: Layout Components

**Files:**
- Create: `frontend/src/components/layout/TopBar.tsx`
- Create: `frontend/src/components/layout/FileTree.tsx`
- Create: `frontend/src/components/layout/StatusBar.tsx`
- Create: `frontend/src/components/layout/RightPanel.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Implement TopBar**

```tsx
// layout/TopBar.tsx
import { useProjectStore } from '../../store/projectStore';
import { api } from '../../lib/api';
import { FolderOpen, Play, Code2, Settings } from 'lucide-react';

export function TopBar() {
  const project = useProjectStore((s) => s.project);
  const setProject = useProjectStore((s) => s.setProject);
  const setActiveTab = useProjectStore((s) => s.setActiveTab);

  const createProject = async () => {
    const name = prompt('Project name?');
    if (!name) return;
    const p = await api.createProject(name);
    setProject(p);
  };

  return (
    <div className="flex items-center gap-4 px-4 py-2 border-b bg-background">
      <span className="font-semibold">{project?.name || 'Senza Studio'}</span>
      <button onClick={createProject} className="text-sm flex items-center gap-1">
        <FolderOpen size={16} /> New
      </button>
      <div className="flex-1" />
      <button onClick={() => setActiveTab('code')} className="text-sm flex items-center gap-1">
        <Code2 size={16} /> Code
      </button>
      <button onClick={() => setActiveTab('run')} className="text-sm flex items-center gap-1">
        <Play size={16} /> Run
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Implement FileTree**

```tsx
// layout/FileTree.tsx
import { useProjectStore } from '../../store/projectStore';
import { useEffect } from 'react';

export function FileTree() {
  const project = useProjectStore((s) => s.project);
  const files = useProjectStore((s) => s.files);
  const loadFiles = useProjectStore((s) => s.loadFiles);
  const setActiveTab = useProjectStore((s) => s.setActiveTab);

  useEffect(() => {
    if (project) loadFiles();
  }, [project, loadFiles]);

  return (
    <div className="w-48 border-r overflow-y-auto">
      <div className="px-2 py-1 text-xs text-muted-foreground">FILES</div>
      {Object.keys(files).map((path) => (
        <button
          key={path}
          onClick={() => setActiveTab('code')}
          className="block w-full text-left px-3 py-1 text-sm hover:bg-accent"
        >
          {path}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Implement StatusBar + RightPanel**

```tsx
// layout/StatusBar.tsx
export function StatusBar() {
  const runStatus = useProjectStore((s) => s.runStatus);
  const activeRunId = useProjectStore((s) => s.activeRunId);
  return (
    <div className="border-t px-4 py-1 text-xs flex gap-4">
      <span>Status: {runStatus}</span>
      {activeRunId && <span>Run: {activeRunId.slice(0, 8)}</span>}
    </div>
  );
}
```

```tsx
// layout/RightPanel.tsx
import { useProjectStore } from '../../store/projectStore';

export function RightPanel() {
  const conversationStatus = useProjectStore((s) => s.conversationStatus);
  const currentSpec = useProjectStore((s) => s.currentSpec);
  const liveEvents = useProjectStore((s) => s.liveEvents);
  const activeTab = useProjectStore((s) => s.activeTab);

  return (
    <div className="w-72 border-l overflow-y-auto">
      {activeTab === 'converse' && (
        <div className="p-2">
          <div className="text-xs text-muted-foreground mb-2">SPEC PREVIEW</div>
          {currentSpec ? (
            <pre className="text-xs bg-muted p-2 rounded">
              {JSON.stringify(currentSpec, null, 2)}
            </pre>
          ) : (
            <p className="text-sm text-muted-foreground">No spec yet. Conversation status: {conversationStatus}</p>
          )}
        </div>
      )}
      {(activeTab === 'run' || activeTab === 'trace') && (
        <div className="p-2">
          <div className="text-xs text-muted-foreground mb-2">EVENTS ({liveEvents.length})</div>
          <div className="space-y-1">
            {liveEvents.slice(-20).map((ev, i) => (
              <div key={i} className="text-xs font-mono">
                {ev.type}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Update App.tsx**

```tsx
import { TopBar } from './components/layout/TopBar';
import { FileTree } from './components/layout/FileTree';
import { StatusBar } from './components/layout/StatusBar';
import { RightPanel } from './components/layout/RightPanel';
import { ConverseTab } from './components/converse/ConverseTab';
import { RunTab } from './components/run/RunTab';
import { CodeTab } from './components/code/CodeTab';
import { DagTab } from './components/dag/DagTab';
import { TraceTab } from './components/trace/TraceTab';
import { useProjectStore } from './store/projectStore';

function App() {
  const activeTab = useProjectStore((s) => s.activeTab);

  return (
    <div className="h-screen flex flex-col">
      <TopBar />
      <div className="flex-1 flex overflow-hidden">
        <FileTree />
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex border-b">
            {(['converse', 'run', 'code', 'dag', 'trace'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => useProjectStore.getState().setActiveTab(tab)}
                className={`px-4 py-2 text-sm ${activeTab === tab ? 'border-b-2 border-primary font-medium' : ''}`}
              >
                {tab === 'converse' ? '对话' : tab === 'run' ? '运行' : tab === 'code' ? '代码' : tab === 'dag' ? 'DAG' : 'Trace'}
              </button>
            ))}
          </div>
          <div className="flex-1 overflow-hidden">
            {activeTab === 'converse' && <ConverseTab />}
            {activeTab === 'run' && <RunTab />}
            {activeTab === 'code' && <CodeTab />}
            {activeTab === 'dag' && <DagTab />}
            {activeTab === 'trace' && <TraceTab />}
          </div>
        </div>
        <RightPanel />
      </div>
      <StatusBar />
    </div>
  );
}

export default App;
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: add layout components and App shell"
```

---

### Task 7: Converse Tab (components/converse/ConverseTab.tsx)

**Files:**
- Create: `frontend/src/components/converse/ConverseTab.tsx`

**Design doc reference:** §5 对话 Tab

- [ ] **Step 1: Implement ConverseTab**

```tsx
import { useState, useRef, useEffect } from 'react';
import { useProjectStore } from '../../store/projectStore';
import { useConverseWs } from '../../hooks/useConverseWs';

export function ConverseTab() {
  const [input, setInput] = useState('');
  const conversation = useProjectStore((s) => s.conversation);
  const status = useProjectStore((s) => s.conversationStatus);
  const sendMessage = useProjectStore((s) => s.sendMessage);
  const { send } = useConverseWs();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [conversation]);

  const handleSubmit = () => {
    if (!input.trim() || status === 'streaming') return;
    sendMessage(input);
    send(input);
    setInput('');
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {conversation.map((msg, i) => (
          <div key={i} className={msg.role === 'user' ? 'text-right' : ''}>
            <div className={`inline-block max-w-[80%] px-3 py-2 rounded-lg ${
              msg.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted'
            }`}>
              <pre className="whitespace-pre-wrap text-sm">{msg.content}</pre>
            </div>
          </div>
        ))}
        {status === 'streaming' && (
          <div className="text-sm text-muted-foreground">●●● streaming...</div>
        )}
        <div ref={endRef} />
      </div>
      <div className="border-t p-2 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder="描述你想构建的 agent..."
          className="flex-1 px-3 py-2 bg-background border rounded"
          disabled={status === 'streaming'}
        />
        <button onClick={handleSubmit} disabled={status === 'streaming'} className="px-4 py-2 bg-primary text-primary-foreground rounded">
          Send
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "feat: add Converse tab"
```

---

### Task 8: Run Tab — Chat View + Execution View

**Files:**
- Create: `frontend/src/components/run/RunTab.tsx`
- Create: `frontend/src/components/run/ChatView.tsx`
- Create: `frontend/src/components/run/ExecutionView.tsx`

**Design doc reference:** §5 运行 Tab (聊天视图 + 执行视图)

- [ ] **Step 1: Implement RunTab dispatcher**

```tsx
// run/RunTab.tsx
import { useProjectStore } from '../../store/projectStore';
import { ChatView } from './ChatView';
import { ExecutionView } from './ExecutionView';

export function RunTab() {
  const runView = useProjectStore((s) => s.runView);
  const runStatus = useProjectStore((s) => s.runStatus);

  if (runStatus === 'idle') {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <p className="text-muted-foreground mb-4">No active run</p>
          <RunControls />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <RunControls />
      {runView === 'chat' ? <ChatView /> : <ExecutionView />}
    </div>
  );
}

function RunControls() {
  const startRun = useProjectStore((s) => s.startRun);
  const stopRun = useProjectStore((s) => s.stopRun);
  const runStatus = useProjectStore((s) => s.runStatus);

  return (
    <div className="flex gap-2 p-2 border-b">
      <button
        onClick={() => startRun('studio')}
        disabled={runStatus === 'running'}
        className="px-3 py-1 text-sm bg-primary text-primary-foreground rounded"
      >
        Studio Run
      </button>
      <button
        onClick={() => startRun('standalone')}
        disabled={runStatus === 'running'}
        className="px-3 py-1 text-sm border rounded"
      >
        Standalone Run
      </button>
      {runStatus === 'running' && (
        <button
          onClick={stopRun}
          className="px-3 py-1 text-sm bg-destructive text-destructive-foreground rounded"
        >
          Stop
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Implement ChatView**

```tsx
// run/ChatView.tsx
import { useState, useRef, useEffect } from 'react';
import { useProjectStore } from '../../store/projectStore';
import { useRunWs } from '../../hooks/useRunWs';

export function ChatView() {
  const [input, setInput] = useState('');
  const messages = useProjectStore((s) => s.runMessages);
  const runStatus = useProjectStore((s) => s.runStatus);
  const sendRunMessage = useProjectStore((s) => s.sendRunMessage);
  const { sendInput } = useRunWs();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSubmit = () => {
    if (!input.trim()) return;
    sendRunMessage(input);
    sendInput(input);
    setInput('');
  };

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((msg, i) => (
          <div key={i} className={msg.role === 'user' ? 'text-right' : ''}>
            <div className={`inline-block max-w-[80%] px-3 py-2 rounded-lg ${
              msg.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted'
            }`}>
              <pre className="whitespace-pre-wrap text-sm">{msg.content}</pre>
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <div className="border-t p-2 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder="输入消息..."
          className="flex-1 px-3 py-2 bg-background border rounded"
          disabled={runStatus !== 'waiting_input' && runStatus !== 'running'}
        />
        <button onClick={handleSubmit} className="px-4 py-2 bg-primary text-primary-foreground rounded">
          Send
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Implement ExecutionView**

```tsx
// run/ExecutionView.tsx
import { useState } from 'react';
import { useProjectStore } from '../../store/projectStore';
import { useRunWs } from '../../hooks/useRunWs';
import { Play, Square } from 'lucide-react';

export function ExecutionView() {
  const [taskInput, setTaskInput] = useState('');
  const stepStates = useProjectStore((s) => s.stepStates);
  const activeStepId = useProjectStore((s) => s.activeStepId);
  const runMessages = useProjectStore((s) => s.runMessages);
  const runStatus = useProjectStore((s) => s.runStatus);
  const submitTask = useProjectStore((s) => s.submitTask);
  const stopRun = useProjectStore((s) => s.stopRun);
  const { sendInput } = useRunWs();

  const handleSubmit = () => {
    if (!taskInput.trim()) return;
    submitTask(taskInput);
    sendInput(taskInput);
    setTaskInput('');
  };

  const steps = Object.entries(stepStates);

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Input area */}
      <div className="flex gap-2 p-2 border-b">
        <input
          value={taskInput}
          onChange={(e) => setTaskInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder="提交任务..."
          className="flex-1 px-3 py-2 bg-background border rounded"
          disabled={runStatus === 'running'}
        />
        <button onClick={handleSubmit} disabled={runStatus === 'running'} className="px-4 py-2 bg-primary text-primary-foreground rounded flex items-center gap-1">
          <Play size={16} /> Run
        </button>
        {runStatus === 'running' && (
          <button onClick={stopRun} className="px-3 py-2 bg-destructive text-destructive-foreground rounded flex items-center gap-1">
            <Square size={16} /> Stop
          </button>
        )}
      </div>

      {/* Inline DAG */}
      <div className="p-4 border-b">
        <div className="flex items-center gap-2 flex-wrap">
          {steps.map(([stepId, state], i) => (
            <div key={stepId} className="flex items-center gap-2">
              {i > 0 && <span className="text-muted-foreground">→</span>}
              <div className={`px-3 py-1 rounded border ${
                state.status === 'done' ? 'bg-green-100 border-green-500' :
                state.status === 'running' ? 'bg-yellow-100 border-yellow-500 animate-pulse' :
                state.status === 'failed' ? 'bg-red-100 border-red-500' :
                'bg-background'
              }`}>
                <div className="text-sm font-medium">{stepId}</div>
                <div className="text-xs text-muted-foreground">{state.status}</div>
                {state.structured && (
                  <pre className="text-xs mt-1">{JSON.stringify(state.structured, null, 2).slice(0, 100)}</pre>
                )}
              </div>
            </div>
          ))}
          {steps.length === 0 && <span className="text-sm text-muted-foreground">Submit a task to start</span>}
        </div>
      </div>

      {/* Current step output */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="text-xs text-muted-foreground mb-2">
          {activeStepId ? `Step: ${activeStepId}` : 'Output'}
        </div>
        {runMessages
          .filter((m) => m.role === 'assistant')
          .slice(-1)
          .map((msg, i) => (
            <pre key={i} className="text-sm whitespace-pre-wrap">{msg.content}</pre>
          ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: add Run tab with ChatView and ExecutionView"
```

---

### Task 9: Code Tab, DAG Tab, Trace Tab

**Files:**
- Create: `frontend/src/components/code/CodeTab.tsx`
- Create: `frontend/src/components/dag/DagTab.tsx`
- Create: `frontend/src/components/trace/TraceTab.tsx`

- [ ] **Step 1: Implement CodeTab**

```tsx
// code/CodeTab.tsx
import { useState, useEffect } from 'react';
import { useProjectStore } from '../../store/projectStore';

export function CodeTab() {
  const files = useProjectStore((s) => s.files);
  const saveFile = useProjectStore((s) => s.saveFile);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (selectedFile && files[selectedFile] !== undefined) {
      setContent(files[selectedFile]);
      setDirty(false);
    }
  }, [selectedFile, files]);

  const handleSave = async () => {
    if (!selectedFile) return;
    await saveFile(selectedFile, content);
    setDirty(false);
  };

  return (
    <div className="flex h-full">
      <div className="w-48 border-r overflow-y-auto">
        {Object.keys(files).map((path) => (
          <button
            key={path}
            onClick={() => setSelectedFile(path)}
            className={`block w-full text-left px-3 py-1 text-sm hover:bg-accent ${selectedFile === path ? 'bg-accent' : ''}`}
          >
            {path}
          </button>
        ))}
      </div>
      <div className="flex-1 flex flex-col">
        {selectedFile ? (
          <>
            <div className="flex items-center justify-between border-b px-3 py-1">
              <span className="text-sm">{selectedFile} {dirty && '•'}</span>
              <button onClick={handleSave} disabled={!dirty} className="px-3 py-1 text-sm bg-primary text-primary-foreground rounded">
                Save
              </button>
            </div>
            <textarea
              value={content}
              onChange={(e) => { setContent(e.target.value); setDirty(true); }}
              className="flex-1 p-2 font-mono text-sm bg-background resize-none focus:outline-none"
            />
          </>
        ) : (
          <div className="flex items-center justify-center text-muted-foreground">Select a file</div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Implement DagTab**

```tsx
// dag/DagTab.tsx
import { useProjectStore } from '../../store/projectStore';
import { ReactFlow, Background, Controls, type Node, type Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useMemo } from 'react';

export function DagTab() {
  const currentSpec = useProjectStore((s) => s.currentSpec);
  const stepStates = useProjectStore((s) => s.stepStates);

  const { nodes, edges } = useMemo(() => {
    if (!currentSpec?.workflow) return { nodes: [], edges: [] };

    const wf = currentSpec.workflow;
    const nodes: Node[] = wf.steps.map((step, i) => {
      const state = stepStates[step.id];
      const status = state?.status || 'pending';
      return {
        id: step.id,
        position: { x: (i % 3) * 250, y: Math.floor(i / 3) * 150 },
        data: { label: `${step.name}\n${status}` },
        style: {
          background: status === 'done' ? '#dcfce7' : status === 'running' ? '#fef9c3' : status === 'failed' ? '#fee2e2' : '#fff',
        },
      };
    });

    const edges: Edge[] = wf.edges.map((e, i) => ({
      id: `edge-${i}`,
      source: e.from,
      target: e.to,
      label: e.condition ? `${e.condition.op} ${e.condition.pointer} ${JSON.stringify(e.condition.value)}` : undefined,
    }));

    return { nodes, edges };
  }, [currentSpec, stepStates]);

  if (!currentSpec?.workflow) {
    return <div className="flex items-center justify-center h-full text-muted-foreground">No workflow (single agent project)</div>;
  }

  return (
    <div className="h-full">
      <ReactFlow nodes={nodes} edges={edges}>
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}
```

- [ ] **Step 3: Implement TraceTab**

```tsx
// trace/TraceTab.tsx
import { useState, useEffect } from 'react';
import { useProjectStore } from '../../store/projectStore';
import { api } from '../../lib/api';

export function TraceTab() {
  const project = useProjectStore((s) => s.project);
  const [runs, setRuns] = useState<string[]>([]);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [events, setEvents] = useState<any[]>([]);

  useEffect(() => {
    if (!project) return;
    api.listRuns(project.id).then(setRuns);
  }, [project]);

  useEffect(() => {
    if (!project || !selectedRun) return;
    api.getRunEvents(project.id, selectedRun).then(setEvents);
  }, [project, selectedRun]);

  return (
    <div className="flex h-full">
      <div className="w-48 border-r overflow-y-auto">
        <div className="px-2 py-1 text-xs text-muted-foreground">RUNS</div>
        {runs.map((runId) => (
          <button
            key={runId}
            onClick={() => setSelectedRun(runId)}
            className={`block w-full text-left px-3 py-1 text-sm hover:bg-accent ${selectedRun === runId ? 'bg-accent' : ''}`}
          >
            {runId.slice(0, 8)}
          </button>
        ))}
        {runs.length === 0 && <div className="px-3 py-1 text-sm text-muted-foreground">No runs yet</div>}
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {events.length === 0 ? (
          <div className="text-muted-foreground">Select a run or run a project first</div>
        ) : (
          <div className="space-y-1">
            {events.map((ev, i) => (
              <div
                key={i}
                className={`text-xs font-mono px-2 py-1 rounded ${
                  ev.type === 'error' ? 'bg-red-100' : 'bg-muted'
                }`}
              >
                {JSON.stringify(ev)}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: add Code, DAG, and Trace tabs"
```

---

### Task 10: Example Picker + Final Wiring

**Files:**
- Create: `frontend/src/components/examples/ExamplePicker.tsx`
- Modify: `frontend/src/components/layout/TopBar.tsx` (add example button)

- [ ] **Step 1: Implement ExamplePicker**

```tsx
// examples/ExamplePicker.tsx
import { useState, useEffect } from 'react';
import { api } from '../../lib/api';
import { useProjectStore } from '../../store/projectStore';
import type { ExampleProject } from '../../types';

export function ExamplePicker({ onClose }: { onClose: () => void }) {
  const [examples, setExamples] = useState<ExampleProject[]>([]);
  const setProject = useProjectStore((s) => s.setProject);

  useEffect(() => {
    api.listExamples().then(setExamples);
  }, []);

  const handleSelect = async (ex: ExampleProject) => {
    const name = prompt('Project name?', ex.name);
    if (!name) return;
    const res = await api.createFromExample(ex.id, name);
    const project = await api.getProject(res.project_id);
    setProject(project);
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-background rounded-lg p-6 max-w-2xl w-full max-h-[80vh] overflow-y-auto">
        <h2 className="text-lg font-semibold mb-4">从示例开始</h2>
        <div className="grid grid-cols-2 gap-3">
          {examples.map((ex) => (
            <button
              key={ex.id}
              onClick={() => handleSelect(ex)}
              className="text-left p-3 border rounded hover:bg-accent"
            >
              <div className="font-medium text-sm">{ex.name}</div>
              <div className="text-xs text-muted-foreground">{ex.description}</div>
              <div className="flex gap-1 mt-1">
                {ex.tags.map((tag) => (
                  <span key={tag} className="text-xs bg-muted px-1.5 py-0.5 rounded">{tag}</span>
                ))}
              </div>
            </button>
          ))}
        </div>
        <button onClick={onClose} className="mt-4 px-4 py-2 text-sm border rounded">Cancel</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add to TopBar**

```tsx
// In TopBar.tsx, add:
import { ExamplePicker } from '../examples/ExamplePicker';
const [showExamples, setShowExamples] = useState(false);
// Add button: <button onClick={() => setShowExamples(true)}>示例库</button>
// Add: {showExamples && <ExamplePicker onClose={() => setShowExamples(false)} />}
```

- [ ] **Step 3: Verify build**

```bash
cd frontend && npm run build
```
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: add ExamplePicker and complete frontend"
```
