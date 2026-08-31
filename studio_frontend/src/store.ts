// studio_frontend/src/store.ts
import { create } from "zustand";
import type {
  ProjectMeta,
  Spec,
  ChatMessage,
  StudioStatus,
  Step,
  GameCard,
  StepRunStatus,
} from "./types";

interface StudioStore {
  project: ProjectMeta | null;
  spec: Spec;
  status: StudioStatus;
  messages: ChatMessage[];
  selectedStep: Step | null;
  ws: WebSocket | null;
  stepStatus: Record<string, StepRunStatus>;
  gameCards: GameCard[];

  setProject: (p: ProjectMeta | null) => void;
  setSpec: (s: Spec) => void;
  setStatus: (s: StudioStatus) => void;
  addMessage: (m: ChatMessage) => void;
  setMessages: (msgs: ChatMessage[]) => void;
  appendToLastAssistant: (text: string) => void;
  selectStep: (s: Step | null) => void;
  setWs: (ws: WebSocket | null) => void;
  resetPlay: () => void;
  startStep: (stepId: string, stepName: string) => void;
  appendStepText: (stepId: string, text: string) => void;
  finishStep: (stepId: string, output?: string) => void;
  failRunningSteps: () => void;
}

export const useStudioStore = create<StudioStore>((set) => ({
  project: null,
  spec: { stages: [] },
  status: "idle",
  messages: [],
  selectedStep: null,
  ws: null,
  stepStatus: {},
  gameCards: [],

  setProject: (project) => set({ project }),
  setSpec: (spec) => set({ spec }),
  setStatus: (status) => set({ status }),
  addMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  setMessages: (messages) => set({ messages }),
  selectStep: (selectedStep) => set({ selectedStep }),
  setWs: (ws) => set({ ws }),
  appendToLastAssistant: (text) =>
    set((s) => {
      const msgs = s.messages;
      if (msgs.length > 0 && msgs[msgs.length - 1].role === "assistant") {
        const updated = [...msgs];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: updated[updated.length - 1].content + text,
        };
        return { messages: updated };
      }
      return {
        messages: [
          ...msgs,
          { role: "assistant", content: text, timestamp: Date.now() },
        ],
      };
    }),

  resetPlay: () => set({ stepStatus: {}, gameCards: [] }),

  startStep: (stepId, stepName) =>
    set((s) => ({
      stepStatus: { ...s.stepStatus, [stepId]: "running" },
      gameCards: [...s.gameCards, { stepId, stepName, text: "", status: "running" }],
    })),

  appendStepText: (stepId, text) =>
    set((s) => {
      const cards = s.gameCards;
      const idx = [...cards].reverse().findIndex((c) => c.stepId === stepId);
      if (idx === -1) return {};
      const realIdx = cards.length - 1 - idx;
      const updated = [...cards];
      updated[realIdx] = { ...updated[realIdx], text: updated[realIdx].text + text };
      return { gameCards: updated };
    }),

  finishStep: (stepId, output) =>
    set((s) => ({
      stepStatus: { ...s.stepStatus, [stepId]: "done" },
      gameCards: s.gameCards.map((c) =>
        c.stepId === stepId && c.status === "running"
          ? { ...c, status: "done", text: output ?? c.text }
          : c
      ),
    })),

  failRunningSteps: () =>
    set((s) => {
      const nextStatus = { ...s.stepStatus };
      for (const [id, st] of Object.entries(nextStatus)) {
        if (st === "running") nextStatus[id] = "error";
      }
      return {
        stepStatus: nextStatus,
        gameCards: s.gameCards.map((c) =>
          c.status === "running" ? { ...c, status: "error" } : c
        ),
      };
    }),
}));
