import { create } from 'zustand';
import type { Message, StudioEvent, StepState, RunStatus, RunView } from '../types';
import { strField, stepIdField, resultField } from '../types';
import { api } from '../lib/api';

interface AgentWindowState {
  projectId: string | null;
  setProjectId: (id: string) => void;

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
  onRunEvent: (event: StudioEvent) => void;
}

export const useAgentStore = create<AgentWindowState>((set, get) => ({
  projectId: null,
  setProjectId: (id) => set({ projectId: id }),

  activeRunId: null,
  runStatus: 'idle',
  runView: 'chat',
  runMessages: [],
  liveEvents: [],
  stepStates: {},
  activeStepId: null,

  startRun: async (mode) => {
    const projectId = get().projectId;
    if (!projectId) return;
    const res = await api.runProject(projectId, mode);
    // Determine run view from spec
    let runView: RunView = 'chat';
    try {
      const files = await api.listFiles(projectId);
      if (files.includes('spec.json')) {
        const specText = await api.readFile(projectId, 'spec.json');
        const spec = JSON.parse(specText) as { agent_type?: string };
        if (spec.agent_type?.includes('workflow')) {
          runView = 'execution';
        }
      }
    } catch {
      // Default to chat view
    }
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
    const projectId = get().projectId;
    const runId = get().activeRunId;
    if (!projectId || !runId) return;
    try {
      await api.stopRun(projectId, runId);
    } catch (e) {
      console.error('stop failed:', e);
    }
    set({ runStatus: 'idle' });
  },

  addRunEvent: (event) =>
    set((s) => ({ liveEvents: [...s.liveEvents, event] })),

  setRunStatus: (s) => set({ runStatus: s }),

  onRunEvent: (event) => {
    get().addRunEvent(event);
    const type = event.type;

    if (type === 'thinking_delta') {
      const text = strField(event, 'thinking');
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
    } else if (type === 'text_delta') {
      // True incremental text — append
      const text = strField(event, 'text');
      if (text) {
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
      }
    } else if (type === 'message_update') {
      // MessageUpdate carries accumulated partial text — only replace if longer
      const text = strField(event, 'text');
      set((s) => {
        const msgs = [...s.runMessages];
        const last = msgs[msgs.length - 1];
        if (last && last.role === 'assistant') {
          // Only replace if the accumulated text is longer than what we have
          if (text.length > last.content.length) {
            msgs[msgs.length - 1] = { ...last, content: text };
          }
        } else if (text) {
          msgs.push({ role: 'assistant', content: text });
        }
        return { runMessages: msgs };
      });
    } else if (type === 'message_end') {
      // MessageEnd carries final text — replace
      const text = strField(event, 'text');
      if (text) {
        set((s) => {
          const msgs = [...s.runMessages];
          const last = msgs[msgs.length - 1];
          if (last && last.role === 'assistant') {
            msgs[msgs.length - 1] = { ...last, content: text };
          } else {
            msgs.push({ role: 'assistant', content: text });
          }
          return { runMessages: msgs };
        });
      }
    } else if (type === 'stdout') {
      // Debug output from stdout — append to last assistant message
      const text = strField(event, 'text');
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
    } else if (type === 'stderr') {
      const text = strField(event, 'text');
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
      const stepId = stepIdField(event);
      if (stepId) {
        set((s) => ({
          activeStepId: stepId,
          stepStates: {
            ...s.stepStates,
            [stepId]: { ...s.stepStates[stepId], status: 'running' },
          },
        }));
      }
    } else if (type === 'step_finished') {
      const stepId = stepIdField(event);
      const result = resultField(event);
      if (stepId) {
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
      }
    } else if (type === 'paused') {
      set({ runStatus: 'waiting_input' });
    } else if (type === 'failed' || type === 'cancelled') {
      set({ runStatus: 'failed' });
    } else if (type === 'done') {
      set({ runStatus: 'completed' });
    }
  },
}));
