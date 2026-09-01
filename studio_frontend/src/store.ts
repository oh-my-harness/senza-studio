// studio_frontend/src/store.ts
import { create } from "zustand";
import type {
  ProjectMeta,
  Spec,
  ChatMessage,
  StudioStatus,
  GameCard,
  StepRunStatus,
  LogEntry,
  LogLevel,
  ToolCallEntry,
} from "./types";

interface StudioStore {
  project: ProjectMeta | null;
  spec: Spec;
  status: StudioStatus;
  messages: ChatMessage[];
  // 只存 name，不存整个 Step 对象——存对象快照会在 spec 更新后过期
  // （Inspector 编辑一个字段触发 setSpec，selectedStep 却还指着编辑前的
  // 旧对象），受控输入框的 value 又变回旧值，表现为“打字立刻被吃掉、
  // 光标跳到末尾”。改成存 name，每次都从当前 spec 里现查，永远不会过期。
  selectedStepName: string | null;
  ws: WebSocket | null;
  stepStatus: Record<string, StepRunStatus>;
  gameCards: GameCard[];
  // 运行自然结束（succeeded/failed）后的终态——不自动退出 playing，留给
  // 用户自己看完结果再点 Stop；这个字段只是用来在 UI 上提示"跑完了"。
  runFinishedState: string | null;
  logs: LogEntry[];
  toolCalls: ToolCallEntry[];
  // checker step 暂停等待人工审批时，是哪个 step——非空时 GameView 显示
  // 审批按钮。
  pausedStepId: string | null;
  // engine 是否处于暂停状态（不管原因——checker 审批或控制条手动
  // Pause/Step 都会让这个变 true）。跟 pausedStepId 是两个不同维度：
  // 后者专门只在 checker 审批时才非空，用来单独控制审批横幅。
  enginePaused: boolean;

  setProject: (p: ProjectMeta | null) => void;
  setSpec: (s: Spec) => void;
  setStatus: (s: StudioStatus) => void;
  addMessage: (m: ChatMessage) => void;
  setMessages: (msgs: ChatMessage[]) => void;
  appendToLastAssistant: (text: string) => void;
  selectStep: (name: string | null) => void;
  setWs: (ws: WebSocket | null) => void;
  resetPlay: () => void;
  startStep: (stepId: string, stepName: string) => void;
  appendStepText: (stepId: string, text: string) => void;
  finishStep: (
    stepId: string,
    output?: string,
    extra?: {
      route?: string;
      debug?: Record<string, unknown> | null;
      fields?: Record<string, unknown> | null;
    }
  ) => void;
  failRunningSteps: () => void;
  setRunFinished: (state: string | null) => void;
  addLog: (level: LogLevel, message: string) => void;
  clearLogs: () => void;
  addToolCall: (entry: ToolCallEntry) => void;
  setToolCalls: (entries: ToolCallEntry[]) => void;
  setPausedStep: (stepId: string | null) => void;
  markAwaitingApproval: (stepId: string, text: string) => void;
  setEnginePaused: (paused: boolean) => void;
}

export const useStudioStore = create<StudioStore>((set) => ({
  project: null,
  spec: { stages: [] },
  status: "idle",
  messages: [],
  selectedStepName: null,
  ws: null,
  stepStatus: {},
  gameCards: [],
  runFinishedState: null,
  logs: [],
  toolCalls: [],
  pausedStepId: null,
  enginePaused: false,

  setProject: (project) => set({ project }),
  setSpec: (spec) => set({ spec }),
  setStatus: (status) => set({ status }),
  addMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  setMessages: (messages) => set({ messages }),
  selectStep: (selectedStepName) => set({ selectedStepName }),
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

  // 点 Play 时调用——顺带清空日志面板，避免上一次运行的日志跟这次的混在一起。
  resetPlay: () =>
    set({
      stepStatus: {},
      gameCards: [],
      runFinishedState: null,
      logs: [],
      pausedStepId: null,
      enginePaused: false,
    }),

  setPausedStep: (pausedStepId) => set({ pausedStepId }),
  setEnginePaused: (enginePaused) => set({ enginePaused }),

  setRunFinished: (runFinishedState) => set({ runFinishedState }),

  addLog: (level, message) =>
    set((s) => ({
      logs: [...s.logs, { level, message, timestamp: Date.now() }],
    })),

  clearLogs: () => set({ logs: [] }),

  addToolCall: (entry) => set((s) => ({ toolCalls: [...s.toolCalls, entry] })),

  setToolCalls: (toolCalls) => set({ toolCalls }),

  startStep: (stepId, stepName) =>
    set((s) => {
      const last = [...s.gameCards].reverse().find((c) => c.stepId === stepId);
      if (last && last.status === "running") {
        // checker step 暂停后被 resume 重新 run()，同一个 step 会再收到一次
        // step_started——这不是新 step，别再插一张重复卡片。
        return {};
      }
      return {
        stepStatus: { ...s.stepStatus, [stepId]: "running" },
        gameCards: [...s.gameCards, { stepId, stepName, text: "", status: "running" }],
      };
    }),

  // checker step 卡在"等审批"时用这个，而不是 finishStep——它不是真的
  // 执行完了，只是这一轮 run() 提前退出；卡片状态留在 running，好让
  // resume 之后的 step_finished 命中 finishStep 里 "status === running"
  // 的更新条件，原地刷新同一张卡片而不是留一张永远过期的卡片。
  markAwaitingApproval: (stepId, text) =>
    set((s) => {
      const cards = s.gameCards;
      const idx = [...cards].reverse().findIndex((c) => c.stepId === stepId);
      if (idx === -1) return {};
      const realIdx = cards.length - 1 - idx;
      const updated = [...cards];
      updated[realIdx] = { ...updated[realIdx], text, status: "running" };
      return { gameCards: updated };
    }),

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

  finishStep: (stepId, output, extra) =>
    set((s) => ({
      stepStatus: { ...s.stepStatus, [stepId]: "done" },
      gameCards: s.gameCards.map((c) =>
        c.stepId === stepId && c.status === "running"
          ? {
              ...c,
              status: "done",
              text: output ?? c.text,
              route: extra?.route,
              debug: extra?.debug,
              fields: extra?.fields,
            }
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
