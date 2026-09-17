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
  ExecRow,
  ExecToolRow,
  ExecPhase,
} from "./types";

// 执行时间线保留上限(约 500 行)——超出时从头部裁掉旧行。execIndex 只记
// 关联键 -> 当前行引用,行被裁掉后键仍指向同一个对象引用,只要裁剪不改写
// 保留行的对象,索引就不用跟着重建;但键会泄漏,所以行数超限后把"索引里
// 指向已裁剪行"的键一并清掉。
const EXEC_MAX_ROWS = 500;

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
  // checker step 暂停等待人工审批时，是哪个 step——非空时 GameView 显示
  // 审批按钮。
  pausedStepId: string | null;
  // engine 是否处于暂停状态（不管原因——checker 审批或控制条手动
  // Pause/Step 都会让这个变 true）。跟 pausedStepId 是两个不同维度：
  // 后者专门只在 checker 审批时才非空，用来单独控制审批横幅。
  // Play 工具执行时间线 + 关联索引(key = `${step_id}:${tool_use_id}`)。
  // index 值是行对象引用而不是下标——行对象一旦创建就不改 identity,更新
  // 时替换引用并同步 index,UI 侧按 seq 排序展示,不怕裁剪导致的位移。
  execRows: ExecRow[];
  execIndex: Record<string, ExecToolRow>;
  // 下一条执行记录的全局序号(裁剪不回退)
  execSeq: number;
  enginePaused: boolean;

  setProject: (p: ProjectMeta | null) => void;
  setSpec: (s: Spec) => void;
  setRuntimeSpec: (s: Spec | null) => void;
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
  handleExecEvent: (event: Record<string, unknown>) => void;
  finalizeInFlightExec: (reason: string) => void;
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

// 把一条新执行行追加到时间线尾部;超过 EXEC_MAX_ROWS 时从头部裁剪旧行。
// execIndex 里指向被裁行的键一并清掉(保留行对象引用不变,键无需重建)。
function appendExecRow(
  s: { execRows: ExecRow[]; execIndex: Record<string, ExecToolRow>; execSeq: number },
  row: ExecRow
): { execRows: ExecRow[]; execIndex: Record<string, ExecToolRow>; execSeq: number } {
  let rows = [...s.execRows, row];
  const index = { ...s.execIndex };
  if (row.kind === "tool") index[row.key] = row;
  if (rows.length > EXEC_MAX_ROWS) {
    const dropped = rows.slice(0, rows.length - EXEC_MAX_ROWS);
    rows = rows.slice(rows.length - EXEC_MAX_ROWS);
    for (const r of dropped) {
      if (r.kind === "tool") delete index[r.key];
    }
  }
  return { execRows: rows, execIndex: index, execSeq: s.execSeq + 1 };
}

// 用新对象替换一条已有的工具记录(execIndex 同步指向新对象)。
function replaceExecRow(
  s: { execRows: ExecRow[]; execIndex: Record<string, ExecToolRow> },
  updated: ExecToolRow
): { execRows: ExecRow[]; execIndex: Record<string, ExecToolRow> } {
  return {
    execRows: s.execRows.map((r) =>
      r.kind === "tool" && r.key === updated.key ? updated : r
    ),
    execIndex: { ...s.execIndex, [updated.key]: updated },
  };
}

export const useStudioStore = create<StudioStore>((set) => ({
  project: null,
  execRows: [],
  execIndex: {},
  execSeq: 1,
  spec: { stages: [] },
  runtimeSpec: null,
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
  setRuntimeSpec: (runtimeSpec) => set({ runtimeSpec }),
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

  // 点 Play 时调用——顺带清空日志面板,避免上一次运行的日志跟这次的混在一起。
  resetPlay: () =>
    set({
      stepStatus: {},
      gameCards: [],
      runFinishedState: null,
      logs: [],
      execRows: [],
      execIndex: {},
      execSeq: 1,
      pausedStepId: null,
      enginePaused: false,
      // 上一次运行的展开结果不能留到下一次——spec 改了组件参数/换了组件，
      // 留着会让审批按钮和 ui 配置停在旧的展开上。
      runtimeSpec: null,
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

  // ---- 执行可观测性 V1--------------------------------------------------
  //
  // Play 路径的工具事件(带 step_id)按 `${step_id}:${tool_use_id}` 关联成
  // 一条记录,生命周期 calling -> executing -> done/failed。设计要点:
  //
  // - 事件乱序/缺失容忍:execution_start 没等到 tool_call_start、execution_end
  //   没等到前两者,都直接合成记录并标 missingStart(旧 v1 Trace 的行为参照)。
  // - turn_end 不参与关联,直接插一条分隔标记。
  // - 行一旦进入列表 identity 不变,更新时用新对象替换并同步 execIndex 里
  //   的引用;裁剪只从头删,execIndex 里指向已删行的键清掉,保留行的键不动。
  //
  // 事件字段跟后端转发保持一致(见 senza-studio-runtime/play.py
  // _run_agent_step + probe 验证):tool_call_start 带 name,tool_call_end 带
  // args(JSON 字符串),tool_execution_start 带 tool_name,
  // tool_execution_end 带 ok/error,turn_end 带 index。
  handleExecEvent: (event) =>
    set((s) => {
      const type = event.type;
      const stepId = typeof event.step_id === "string" ? event.step_id : null;
      const toolUseId =
        typeof event.tool_use_id === "string" ? event.tool_use_id : null;
      // 每种事件的有效载荷解析都在这里做完,后面不再碰 event
      const toolNameFromCall =
        typeof event.name === "string" ? event.name : null;
      const toolNameFromExec =
        typeof event.tool_name === "string" ? event.tool_name : null;
      const argsRaw = typeof event.args === "string" ? event.args : null;
      const ok = typeof event.ok === "boolean" ? event.ok : null;
      const error =
        typeof event.error === "string" && event.error.length > 0
          ? event.error
          : null;
      const turnIndex = typeof event.index === "number" ? event.index : 0;

      if (type === "turn_end") {
        if (stepId === null) return {};
        const row: ExecRow = {
          kind: "turn",
          seq: s.execSeq,
          stepId,
          index: turnIndex,
          timestamp: Date.now(),
        };
        return appendExecRow(s, row);
      }

      // 其余四种都要能定位到一条工具记录
      if (stepId === null || toolUseId === null) return {};
      const key = `${stepId}:${toolUseId}`;

      if (type === "tool_call_start") {
        if (toolNameFromCall === null) return {};
        // 重复的 tool_call_start(理论上不该有)不覆盖已有记录
        if (s.execIndex[key]) return {};
        const row: ExecToolRow = {
          kind: "tool",
          seq: s.execSeq,
          key,
          stepId,
          toolUseId,
          toolName: toolNameFromCall,
          argsRaw: null,
          phase: "calling",
          ok: null,
          error: null,
          missingStart: false,
          startedAt: Date.now(),
          endedAt: null,
        };
        return appendExecRow(s, row);
      }

      const existing = s.execIndex[key];

      if (type === "tool_call_end") {
        // args 补挂到已有记录上;孤儿 call_end(没等到 start)合成一条
        // executing 记录——已经过了"调用"阶段才收得到 call_end。
        if (existing) {
          const updated: ExecToolRow = {
            ...existing,
            argsRaw: existing.argsRaw ?? argsRaw,
          };
          return replaceExecRow(s, updated);
        }
        const row: ExecToolRow = {
          kind: "tool",
          seq: s.execSeq,
          key,
          stepId,
          toolUseId,
          toolName: toolNameFromExec ?? "(未知工具)",
          argsRaw,
          phase: "executing",
          ok: null,
          error: null,
          missingStart: true,
          startedAt: Date.now(),
          endedAt: null,
        };
        return appendExecRow(s, row);
      }

      if (type === "tool_execution_start") {
        if (existing) {
          // calling -> executing;乱序再来的 call_end 之后还能补挂 args
          const updated: ExecToolRow = {
            ...existing,
            phase: "executing",
            toolName: existing.toolName || (toolNameFromExec ?? ""),
            missingStart: false,
          };
          return replaceExecRow(s, updated);
        }
        // 孤儿 execution_start:没等到 LLM 发起调用的通知就开跑了
        const row: ExecToolRow = {
          kind: "tool",
          seq: s.execSeq,
          key,
          stepId,
          toolUseId,
          toolName: toolNameFromExec ?? "(未知工具)",
          argsRaw: null,
          phase: "executing",
          ok: null,
          error: null,
          missingStart: true,
          startedAt: Date.now(),
          endedAt: null,
        };
        return appendExecRow(s, row);
      }

      if (type === "tool_execution_end") {
        if (existing) {
          const updated: ExecToolRow = {
            ...existing,
            phase: ok === false ? "failed" : "done",
            ok: ok ?? false,
            error,
            endedAt: Date.now(),
          };
          return replaceExecRow(s, updated);
        }
        // 孤儿 execution_end:三种前置事件全没见到(订阅晚了/事件被截断)
        const row: ExecToolRow = {
          kind: "tool",
          seq: s.execSeq,
          key,
          stepId,
          toolUseId,
          toolName: toolNameFromExec ?? "(未知工具)",
          argsRaw: null,
          phase: ok === false ? "failed" : "done",
          ok: ok ?? false,
          error,
          missingStart: true,
          startedAt: Date.now(),
          endedAt: Date.now(),
        };
        return appendExecRow(s, row);
      }

      return {};
    }),

  // 失败/用户 Stop 时兜底:把所有还挂在 calling/executing 的记录标成
  // failed,错误信息带上原因。不带 step_id 的 failed/cancelled/workflow_done/
  // play_stopped 事件都会走到这里(见 ChatPanel 的事件分发)。
  finalizeInFlightExec: (reason) =>
    set((s) => {
      const hasInFlight = s.execRows.some(
        (r) => r.kind === "tool" && (r.phase === "calling" || r.phase === "executing")
      );
      if (!hasInFlight) return {};
      const index = { ...s.execIndex };
      let changed = false;
      const rows = s.execRows.map((r) => {
        if (r.kind !== "tool" || (r.phase !== "calling" && r.phase !== "executing")) {
          return r;
        }
        changed = true;
        const updated: ExecToolRow = {
          ...r,
          phase: "failed",
          ok: false,
          error: r.error ?? reason,
          endedAt: Date.now(),
        };
        index[updated.key] = updated;
        return updated;
      });
      return changed ? { execRows: rows, execIndex: index } : {};
    }),
}));
