// studio_frontend/src/store.ts
import { create } from "zustand";
import type { ProjectMeta, Spec, ChatMessage, StudioStatus, Step } from "./types";

interface StudioStore {
  project: ProjectMeta | null;
  spec: Spec;
  status: StudioStatus;
  messages: ChatMessage[];
  selectedStep: Step | null;
  ws: WebSocket | null;

  setProject: (p: ProjectMeta | null) => void;
  setSpec: (s: Spec) => void;
  setStatus: (s: StudioStatus) => void;
  addMessage: (m: ChatMessage) => void;
  appendToLastAssistant: (text: string) => void;
  selectStep: (s: Step | null) => void;
  setWs: (ws: WebSocket | null) => void;
}

export const useStudioStore = create<StudioStore>((set) => ({
  project: null,
  spec: { stages: [] },
  status: "idle",
  messages: [],
  selectedStep: null,
  ws: null,

  setProject: (project) => set({ project }),
  setSpec: (spec) => set({ spec }),
  setStatus: (status) => set({ status }),
  addMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
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
}));
