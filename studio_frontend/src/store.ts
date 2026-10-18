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
  // Play 期间后端下发的"实际在跑的 spec"（能力组件已展开）。编辑态 spec
  // 里没有组件生成的 step（gate_review 之类），审批按钮/ui.display/DAG
  // 高亮都得按这份查。不在运行中时为 null，查询处回落到编辑态 spec。
  runtimeSpec: Spec | null;
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
  // checker step 暂停等待人工审批时，是哪个 step——非空时 Game view 显示
  // 审批按钮。
  pausedStepId: string | null;
  // "Play Paused"（从头单步）的标志。Play 按钮只负责**进入运行视图**，真正
  // 的 play 消息是 Game view 里的开始表单发的（那个表单就是导出产品的第一屏，
  // 得在 Studio 里能预览到），所以这个标志要在两者之间传一程。
  playStartPaused: boolean;
  // Play 期间的错误。导出产品把错误显示在界面上，Game view 是它的预览，
  // 所以也得有——只记在日志面板里的话，两边看到的就不是一回事了。
  playError: string | null;
  // engine 是否处于暂停状态（不管原因——checker 审批或控制条手动
  // Pause/Step 都会让这个变 true）。跟 pausedStepId 是两个不同维度：
  // 后者专门只在 checker 审批时才非空，用来单独控制审批横幅。
  enginePaused: boolean;
  // 会话列表。从 ChatPanel 的局部 state 提上来（Phase 7 切片三）：WebSocket
  // 的生命周期要从 ChatPanel 里搬出去（export 模式根本不渲染对话面板），
  // 而消息处理器里唯一还依赖局部 state 的就是 session_switched 这一条。
  sessions: string[];
  activeSession: string | null;
  // 元 agent 是否正在回复。同样是从 ChatPanel 提上来的——WebSocket 处理器
  // 会改它，而处理器已经不住在 ChatPanel 里了。
  streaming: boolean;

  setProject: (p: ProjectMeta | null) => void;
  setSpec: (s: Spec) => void;
  setRuntimeSpec: (s: Spec | null) => void;
  setStatus: (s: StudioStatus) => void;
  addMessage: (m: ChatMessage) => void;
  setMessages: (msgs: ChatMessage[]) => void;
  appendToLastAssistant: (text: string) => void;
  selectStep: (name: string | null) => void;
  setWs: (ws: WebSocket | null) => void;
  // 支持函数式更新：session_switched 要基于当前列表去重追加
  setSessions: (s: string[] | ((prev: string[]) => string[])) => void;
  setActiveSession: (s: string | null) => void;
  setStreaming: (v: boolean) => void;
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
  setPlayStartPaused: (v: boolean) => void;
  setPlayError: (message: string | null) => void;
  markAwaitingApproval: (stepId: string, text: string) => void;
  setEnginePaused: (paused: boolean) => void;
}

export const useStudioStore = create<StudioStore>((set) => ({
  project: null,
  spec: { stages: [] },
  runtimeSpec: null,
  sessions: [],
  activeSession: null,
  streaming: false,
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
  playStartPaused: false,
  playError: null,
  enginePaused: false,

  setProject: (project) => set({ project }),
  setSpec: (spec) => set({ spec }),
  setRuntimeSpec: (runtimeSpec) => set({ runtimeSpec }),
  setStatus: (status) => set({ status }),
  addMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  setMessages: (messages) => set({ messages }),
  selectStep: (selectedStepName) => set({ selectedStepName }),
  setWs: (ws) => set({ ws }),
  setSessions: (value) =>
    set((s) => ({
      sessions:
        typeof value === "function"
          ? (value as (prev: string[]) => string[])(s.sessions)
          : value,
    })),
  setActiveSession: (activeSession) => set({ activeSession }),
  setStreaming: (streaming) => set({ streaming }),
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
      playError: null,
      enginePaused: false,
      // 上一次运行的展开结果不能留到下一次——spec 改了组件参数/换了组件，
      // 留着会让审批按钮和 ui 配置停在旧的展开上。
      runtimeSpec: null,
    }),

  setPausedStep: (pausedStepId) => set({ pausedStepId }),
  setPlayStartPaused: (playStartPaused) => set({ playStartPaused }),
  setPlayError: (playError) => set({ playError }),
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
