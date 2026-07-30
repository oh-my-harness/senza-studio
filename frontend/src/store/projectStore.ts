import { create } from 'zustand';
import type {
  ProjectMeta, Spec, SpecDiff, Message, StudioEvent, StepState,
  RunStatus, RunView, ConversationStatus,
} from '../types';
import { api } from '../lib/api';

interface ProjectStore {
  project: ProjectMeta | null;
  setProject: (p: ProjectMeta) => void;

  files: Record<string, string>;
  dirtyFiles: Set<string>;
  loadFiles: () => Promise<void>;
  saveFile: (path: string, content: string) => Promise<void>;

  conversation: Message[];
  conversationStatus: ConversationStatus;
  currentSpec: Spec | null;
  sendMessage: (text: string) => void;
  addConversationMessage: (msg: Message) => void;
  setConversationStatus: (s: ConversationStatus) => void;
  setCurrentSpec: (s: Spec | null) => void;

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

  generate: () => Promise<void>;
  applySpecDiff: (diff: SpecDiff) => Promise<void>;

  onConverseEvent: (event: StudioEvent) => void;
  onRunEvent: (event: StudioEvent) => void;

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
  },
  addConversationMessage: (msg) =>
    set((s) => ({ conversation: [...s.conversation, msg] })),
  setConversationStatus: (s) => set({ conversationStatus: s }),
  setCurrentSpec: (s) => set({ currentSpec: s }),

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
    set((s) => ({
      runMessages: [...s.runMessages, { role: 'user', content: text }],
    }));
  },
  submitTask: (text) => {
    set((s) => ({
      runMessages: [...s.runMessages, { role: 'user', content: text }],
    }));
  },
  stopRun: async () => {
    const project = get().project;
    const runId = get().activeRunId;
    if (!project || !runId) return;
    try {
      await api.stopRun(project.id, runId);
    } catch (e) {
      console.error('stop failed:', e);
    }
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
    if (type === 'thinking_delta') {
      const text = (event as any).text || '';
      set((s) => {
        const conv = [...s.conversation];
        const last = conv[conv.length - 1];
        if (last && last.role === 'assistant') {
          conv[conv.length - 1] = { ...last, thinking: (last.thinking || '') + text };
        } else {
          conv.push({ role: 'assistant', content: '', thinking: text });
        }
        return { conversation: conv };
      });
    } else if (type === 'text_delta') {
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
    }
  },

  onRunEvent: (event) => {
    get().addRunEvent(event);
    const type = event.type;

    if (type === 'thinking_delta') {
      const text = (event as any).text || '';
      set((s) => {
        const msgs = [...s.runMessages];
        const last = msgs[msgs.length - 1];
        if (last && last.role === 'assistant') {
          msgs[msgs.length - 1] = { ...last, thinking: (last.thinking || '') + text };
        } else {
          msgs.push({ role: 'assistant', content: '', thinking: text });
        }
        return { runMessages: msgs };
      });
    } else
    if (type === 'text_delta') {
      const text = (event as any).text || '';
      set((s) => {
        const msgs = [...s.runMessages];
        const last = msgs[msgs.length - 1];
        // Each stdout line is a separate text_delta — append with newline
        if (last && last.role === 'assistant') {
          msgs[msgs.length - 1] = { ...last, content: last.content + text + '\n' };
        } else {
          msgs.push({ role: 'assistant', content: text + '\n' });
        }
        return { runMessages: msgs };
      });
    } else if (type === 'stderr') {
      const text = (event as any).text || '';
      set((s) => {
        const msgs = [...s.runMessages];
        const last = msgs[msgs.length - 1];
        if (last && last.role === 'assistant') {
          msgs[msgs.length - 1] = { ...last, content: last.content + text + '\n' };
        } else {
          msgs.push({ role: 'assistant', content: text + '\n' });
        }
        return { runMessages: msgs };
      });
    } else if (type === 'input_request') {
      set({ runStatus: 'waiting_input' });
    } else if (type === 'settled') {
      set({ runStatus: 'running' });
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
    } else if (type === 'done') {
      set({ runStatus: 'completed' });
    }
  },

  activeTab: 'converse',
  setActiveTab: (t) => set({ activeTab: t }),
}));
