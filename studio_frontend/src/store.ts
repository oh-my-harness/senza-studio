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
  ExecActivity,
  ExecActivityPhase,
  ConsoleRow,
  ConsoleCategory,
} from "./types";
import {
  CONSOLE_MAX_ROWS,
  CHAT_ACTIVITY_SCOPE,
  PENDING_APPROVAL_ROUTE_KEY,
} from "./types";
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
  // Play 工具执行时间线 + 关联索引(key = `${step_id}:${tool_use_id}`)。
  // index 值是行对象引用而不是下标——行对象一旦创建就不改 identity,更新
  // 时替换引用并同步 index,UI 侧按 seq 排序展示,不怕裁剪导致的位移。
  execRows: ExecRow[];
  execIndex: Record<string, ExecToolRow>;
  // 执行活动(前工具阶段):scope -> 当前活动。scope 是 Play step_id,或
  // 对话路径的 "chat" 伪 step。终态(done/error)保留在表里,UI 用来显示
  // 最后状态;新活动开始时覆盖。
  execActivity: Record<string, ExecActivity>;
  // 平台执行控制台(append-only 时间线):ChatPanel 收到的每条相关事件
  // 映射成一行。currentPromptStartMs 用于 PROMPT completed 的总耗时。
  consoleRows: ConsoleRow[];
  consoleSeq: number;
  consolePromptStart: number | null;
  currentPromptRunId: string | null;
  // 已结算 run 集合(corrKey run:<id> -> true)——终态行去重。PROMPT
  // received 行与终态行共用 corrKey,所以不能按行匹配,要按这个集合。
  consoleResolvedRunIds: Record<string, true>;
  // 下一条执行记录的全局序号(裁剪不回退)
  execSeq: number;
  _consolePending: Map<string, { ts: number }>;
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
  setExecActivity: (scope: string, phase: ExecActivityPhase, message?: string) => void;
  clearExecActivity: (scope: string) => void;
  addConsoleSysRow: (text: string, detail?: string) => void;
  handleConsoleEvent: (event: Record<string, unknown>) => void;
  markConsolePromptStart: (text: string, runId: string) => void;
  markConsolePromptEnd: (reason: string, isError?: boolean, runId?: string) => void;
  handleExecEvent: (event: Record<string, unknown>) => void;
  finalizeInFlightActivity: (reason: string) => void;
  finalizeInFlightExec: (reason: string) => void;
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

// 把一条新执行行追加到时间线尾部;超过 EXEC_MAX_ROWS 时从头部裁剪旧行。
// execIndex 里指向被裁行的键一并清掉(保留行对象引用不变,键无需重建)。
function appendExecRow(
  s: {
    execRows: ExecRow[];
    execIndex: Record<string, ExecToolRow>;
    execSeq: number;
    execActivity: Record<string, ExecActivity>;
  },
  row: ExecRow
): {
  execRows: ExecRow[];
  execIndex: Record<string, ExecToolRow>;
  execSeq: number;
  execActivity: Record<string, ExecActivity>;
} {
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
  return {
    execRows: rows,
    execIndex: index,
    execSeq: s.execSeq + 1,
    execActivity: s.execActivity,
  };
}

// ---- 平台执行控制台(append-only)----------------------------------------
//
// 事件 -> ConsoleRow 的映射/关联集中在这里,ChatPanel 只负责转发。设计:
// - 只追加,不回写旧行;durationMs 靠 start/end 配对(corrKey),配对表在
//   reducer 闭包内逐事件维护。
// - 裁剪同 execRows:超 CONSOLE_MAX_ROWS 从头删,consoleSeq 不回退。
// - 同一事实两条事件不重复入行(如 harness_tool_call_* 与 tool_call_*
//   / tool_execution_* 重复,只保留后者;message_update 与 message_end
//   同义,只保留 end)。
type ConsolePending = Map<string, { ts: number }>;

function appendConsole(
  s: { consoleRows: ConsoleRow[]; consoleSeq: number },
  row: Omit<ConsoleRow, "seq">
): { consoleRows: ConsoleRow[]; consoleSeq: number } {
  let rows = [...s.consoleRows, { ...row, seq: s.consoleSeq }];
  if (rows.length > CONSOLE_MAX_ROWS) {
    rows = rows.slice(rows.length - CONSOLE_MAX_ROWS);
  }
  return { consoleRows: rows, consoleSeq: s.consoleSeq + 1 };
}

function oneLine(text: string, max = 160): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > 200 ? flat.slice(0, 200) + "…(截断)" : flat;
}

// 权威终态行写入(去重 + 计时归属):
// - dedup:同一 run(corrKey = run:<id>)只允许一条终态行——事件分支、
//   后端推送、重连对账三条路径都收敛到这里。
// - 只有匹配 currentPromptRunId 的终态才清 consolePromptStart(当前 prompt
//   计时器);旧 run 的终态只追加行,不影响正在进行的 run。
function markConsoleTerminal(
  s: {
    consoleRows: ConsoleRow[];
    consoleSeq: number;
    consolePromptStart: number | null;
    currentPromptRunId: string | null;
    _consolePending: Map<string, { ts: number }>;
    consoleResolvedRunIds: Record<string, true>;
    execActivity: Record<string, ExecActivity>;
  },
  runId: string | null,
  outcome: "completed" | "failed" | "cancelled",
  reason: string
): Record<string, unknown> {
  const corr = runId !== null ? `run:${runId}` : null;
  // 去重只看"已结算 run 集合"——不能按 corrKey 匹配行:PROMPT received 行
  // 的 corrKey 也是 run:<id>,按行匹配会把收到行误当终态行而跳过写入。
  if (corr !== null && s.consoleResolvedRunIds[corr]) {
    return {};
  }
  const start = s.consolePromptStart;
  const isCurrent = runId !== null && runId === s.currentPromptRunId;
  const isError = outcome !== "completed";
  // cancelled 属于 PROMPT 类(语义是"这次执行被取消",不是系统错误);
  // failed → ERROR 行。
  const category: ConsoleCategory = outcome === "failed" ? "ERROR" : "PROMPT";
  const dur = isCurrentRun(s, runId) && start !== null ? Date.now() - start : null;
  const next = appendConsole(s, {
    timestamp: Date.now(),
    category,
    text: `${outcome}: ${oneLine(reason, 120)}${
      isCurrentRun(s, runId) && start !== null ? ` (${(dur! / 1000).toFixed(1)}s)` : ""
    }`,
    detail: null,
    durationMs: isCurrentRun(s, runId) ? dur : null,
    isError,
    ...(corr !== null ? { corrKey: corr } : {}),
  });
  const resolved = corr !== null ? { ...s.consoleResolvedRunIds, [corr]: true as const } : s.consoleResolvedRunIds;
  // "chat" 活动行的终态:本 run 的权威结果到达 → 结束挂着的活动计时。
  // 覆盖所有挂起状态(waiting_model/model_generating/model_responding/
  // running/compacting)——若活动行是旧 run 的(不同 runId),不动它。
  const chatAct = s.execActivity[CHAT_ACTIVITY_SCOPE];
  let execActivity = s.execActivity;
  if (chatAct && chatAct.phase !== "done" && chatAct.phase !== "error" &&
      (runId === null || chatAct.scope === "chat" && isCurrent)) {
    execActivity = {
      ...s.execActivity,
      [CHAT_ACTIVITY_SCOPE]: {
        scope: "chat",
        phase: isError ? "error" : "done",
        since: chatAct.since,
        message: isError ? reason : null,
      },
    };
  }
  if (!isCurrentRun(s, runId)) {
    return { ...next, consoleResolvedRunIds: resolved, execActivity };
  }
  return {
    ...next,
    consoleResolvedRunIds: resolved,
    consolePromptStart: null,
    currentPromptRunId: null,
    execActivity,
    _consolePending: new Map(),
  };
}

function isCurrentRun(
  s: { currentPromptRunId: string | null },
  runId: string | null
): boolean {
  return runId !== null && s.currentPromptRunId === runId;
}

// markAwaitingApproval 的纯函数版(handleExecEvent 的 gate 消费路径使用):
// step_finished 的 output 为空时（executor 驱动的 agent step 的通病），
// 卡片正文退回流式文本；若流式文本本身是 JSON 提案信封（agent 的结构化
// 回答整个是 {"route":...}），则取结构化字段里最长的文本值（如 narrative）
// 作为人读正文——原始 JSON 属于协议载荷，不该原样展示给玩家。
function isJsonEnvelope(text: string): boolean {
  const t = text.trim();
  if (!t.startsWith("{")) return false;
  try {
    const o = JSON.parse(t);
    return typeof o === "object" && o !== null && !Array.isArray(o);
  } catch {
    return false;
  }
}

function longestTextField(fields: Record<string, unknown> | null | undefined): string | null {
  if (!fields) return null;
  let best: string | null = null;
  for (const v of Object.values(fields)) {
    if (typeof v === "string" && v.trim() && (best === null || v.length > best.length)) {
      best = v;
    }
  }
  return best;
}


// 更新最近一张同 step 卡片的 text,状态保持 running。
function markAwaitingApprovalUpdate(
  s: { gameCards: GameCard[] },
  stepId: string,
  text: string
): { gameCards: GameCard[] } {
  const cards = s.gameCards;
  const idx = [...cards].reverse().findIndex((c) => c.stepId === stepId);
  if (idx === -1) return { gameCards: cards };
  const realIdx = cards.length - 1 - idx;
  const updated = [...cards];
  updated[realIdx] = { ...updated[realIdx], text, status: "running" as const };
  return { gameCards: updated };
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
  spec: { stages: [] },
  execActivity: {},
  consoleRows: [],
  consoleSeq: 1,
  consolePromptStart: null,
  execSeq: 1,
  currentPromptRunId: null,
  consoleResolvedRunIds: {},
  _consolePending: new Map(),
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

  resetPlay: () =>
    set({
      stepStatus: {},
      gameCards: [],
      runFinishedState: null,
      logs: [],
      execRows: [],
      execIndex: {},
      execSeq: 1,
      execActivity: {},
      consoleRows: [],
      consoleSeq: 1,
      consolePromptStart: null,
      currentPromptRunId: null,
      consoleResolvedRunIds: {},
      _consolePending: new Map(),
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

  // 非终态系统行(断连提示等)——append-only 控制台的一部分,不算 PROMPT
  addConsoleSysRow: (text, detail) =>
    set((s) =>
      appendConsole(s, {
        timestamp: Date.now(),
        category: "SYS",
        text: oneLine(text),
        detail: detail ?? null,
        durationMs: null,
        isError: false,
      })
    ),

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
      gameCards: s.gameCards.map((c) => {
        if (!(c.stepId === stepId && c.status === "running")) return c;
        // 事件里的 output 是权威落盘输出（tool step 会带 player_face 级别的
        // 正文）；但 WorkflowEvent::StepFinished 对 executor 驱动的 agent step
        // output 恒为空串（Rust 侧看不到 Python 回调的返回文本）。直接
        // `output ?? c.text` 会把流式正文抹成空卡片——先取非空 output，
        // 否则保留流式文本；若流式文本只是 JSON 提案信封（agent 结构化
        // 回答），用结构化字段里最长的文本字段（如 narrative）作为卡片
        // 正文，绝不让卡片退化成 "…" 或裸 JSON。
        let text = output ?? c.text;
        if (!text || !text.trim()) text = c.text;
        if (isJsonEnvelope(text) && extra?.fields) {
          const best = longestTextField(extra.fields);
          if (best) text = best;
        }
        return {
          ...c,
          status: "done",
          text,
          route: extra?.route,
          debug: extra?.debug,
          fields: extra?.fields,
        };
      }),
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
      const stepName =
        typeof event.step_name === "string" ? event.step_name : null;
      const structured = (event.structured ?? null) as
        | {
            route_key?: string;
            _debug?: Record<string, unknown> | null;
            fields?: Record<string, unknown> | null;
          }
        | null
        | undefined;
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
      const toolUseId =
        typeof event.tool_use_id === "string" ? event.tool_use_id : null;
      const turnIndex = typeof event.index === "number" ? event.index : 0;

      // ---- 活动状态(前工具阶段)------------------------------------
      // scope:带 step_id 的归该 step;不带 step_id 的活动事件(turn_start
      // 等在对话路径不会出现,但 step_started/finished 引擎事件永远带
      // step_id)不该出现在这里,防御性丢弃。
      const activityOf = (scope: string, phase: ExecActivityPhase, message: string | null = null): Record<string, ExecActivity> => ({
        ...s.execActivity,
        [scope]: { scope, phase, since: Date.now(), message },
      });

      if (type === "step_started") {
        if (stepId === null) return {};
        // gate 消费此事件,必须同时驱动两个消费者:观测(execActivity)
        // 与既有 Play UI(gameCards/stepStatus——DAG/GameView/Inspector 的
        // 唯一数据源)。缺一不可,否则观测会"吞掉"既有 UI 的更新。
        // (与 startStep 相同的去重语义:resume 后重复 step_started 不再插卡。)
        const lastCard = [...s.gameCards].reverse().find((c) => c.stepId === stepId);
        const uiUpdate =
          lastCard && lastCard.status === "running"
            ? {}
            : {
                stepStatus: { ...s.stepStatus, [stepId]: "running" as const },
                gameCards: [
                  ...s.gameCards,
                  { stepId, stepName: stepName ?? stepId, text: "", status: "running" as const },
                ],
              };
        return {
          execActivity: activityOf(stepId, "running"),
          ...uiUpdate,
        };
      }
      if (type === "turn_start") {
        if (stepId === null) return {};
        return { execActivity: activityOf(stepId, "waiting_model") };
      }
      if (type === "text_delta") {
        // 带 step_id 的 text_delta 属于 Play step streaming——模型已在响应。
        // 不带 step_id 的走对话路径,由 ChatPanel 处理(不在这里)。
        if (stepId === null) return {};
        const cur = s.execActivity[stepId];
        if (cur && (cur.phase === "done" || cur.phase === "error")) return {};
        return { execActivity: activityOf(stepId, "model_responding") };
      }
      if (type === "compaction_start") {
        if (stepId === null) return {};
        return { execActivity: activityOf(stepId, "compacting") };
      }
      if (type === "compaction_end") {
        if (stepId === null) return {};
        const cur = s.execActivity[stepId];
        // 压缩结束回到等待模型(turn 流程继续,请求即将发出);若已经进入
        // tool 阶段则不回退——tool 事件自己会驱动状态。
        return {
          execActivity: activityOf(
            stepId,
            cur && cur.phase === "running" ? "running" : "waiting_model"
          ),
        };
      }
      if (type === "step_finished") {
        if (stepId === null) return {};
        // 同 step_started:gate 消费此事件,两个消费者都要驱动。
        const output = typeof event.output === "string" ? event.output : null;
        // 审批门(route_key=__pending_approval__)沿用既有链语义:卡片留在
        // running,等 resume 后的终态;观测侧保持 running 而非 done。
        if (structured?.route_key === PENDING_APPROVAL_ROUTE_KEY) {
          return {
            ...markAwaitingApprovalUpdate(s, stepId, output ?? ""),
            execActivity: activityOf(stepId, "running"),
            // gate 消费了 step_finished,hook 链上维护 pausedStepId 的分支
            // 不会执行——审批状态必须在这里原子落位,否则 enginePaused=true
            // 而 pausedStepId=null,GameView 渲染不出 DecisionPanel。
            pausedStepId: stepId,
          };
        }
        return {
          pausedStepId: null,
          stepStatus: { ...s.stepStatus, [stepId]: "done" as const },
          gameCards: s.gameCards.map((c) =>
            c.stepId === stepId && c.status === "running"
              ? {
                  ...c,
                  status: "done" as const,
                  text: output ?? c.text,
                  route: structured?.route_key,
                  debug: structured?._debug,
                  fields: structured?.fields,
                }
              : c
          ),
          execActivity: activityOf(stepId, "done"),
        };
      }

      // 工具事件开始时,若该 step 活动还在 waiting_model/model_responding,
      // 切回 running(工具阶段由 execRows 表达)。
      const toolActivityReset = (
        scope: string
      ): Record<string, ExecActivity> => {
        const cur = s.execActivity[scope];
        if (
          !cur ||
          cur.phase === "running" ||
          cur.phase === "done" ||
          cur.phase === "error"
        ) {
          return {};
        }
        return { [scope]: { ...cur, phase: "running" } };
      };

      if (type === "turn_end") {
        if (stepId === null) return {};
        const row: ExecRow = {
          kind: "turn",
          seq: s.execSeq,
          stepId,
          index: turnIndex,
          timestamp: Date.now(),
        };
        const next = appendExecRow(s, row);
        // turn 结束 = 本轮 LLM 回复完成;下一轮 turn_start 之前仍然是
        // waiting_model(工具跑完接着发下一轮请求,或直接结束)。
        const cur = s.execActivity[stepId];
        if (cur && cur.phase !== "done" && cur.phase !== "error") {
          return {
            ...next,
            execActivity: {
              ...next.execActivity,
              [stepId]: { ...cur, phase: "waiting_model", since: Date.now() },
            },
          };
        }
        return next;
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
        // LLM 开始发起工具调用 = 模型已在响应;活动从 waiting_model/
        // model_responding/compacting 切到 running(工具阶段由 execRows
        // 的 calling/executing 行表达)。
        const activityReset = toolActivityReset(stepId);
        const next = appendExecRow(s, row);
        if (Object.keys(activityReset).length === 0) return next;
        return {
          ...next,
          execActivity: { ...s.execActivity, ...activityReset },
        };
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
  // 活动状态设置(独立于事件流——ChatPanel 的对话路径也用它驱动 "chat"
  // 伪 step 的活动)。
  setExecActivity: (scope, phase, message) =>
    set((s) => ({
      execActivity: {
        ...s.execActivity,
        [scope]: { scope, phase, since: Date.now(), message: message ?? null },
      },
    })),

  clearExecActivity: (scope) =>
    set((s) => {
      if (!(scope in s.execActivity)) return {};
      const next = { ...s.execActivity };
      delete next[scope];
      return { execActivity: next };
    }),

  // ---- 平台执行控制台(append-only)--------------------------------
  // 只映射"对话/平台路径"的事实;带 step_id 的 Play 事件走 handleExecEvent,
  // 不进控制台(Play 有自己的 execRows 时间线)。
  handleConsoleEvent: (event) =>
    set((s) => {
      const type = event.type;
      if (typeof event.step_id === "string" && event.step_id.length > 0) {
        return {}; // Play step 事件,归 execRows
      }
      const now = Date.now();
      const row = (
        category: ConsoleCategory,
        text: string,
        opts: Partial<Pick<ConsoleRow, "detail" | "durationMs" | "isError" | "corrKey">> = {}
      ) => appendConsole(s, {
        timestamp: now,
        category,
        text: oneLine(text),
        detail: opts.detail ?? null,
        durationMs: opts.durationMs ?? null,
        isError: opts.isError ?? false,
        ...(opts.corrKey !== undefined ? { corrKey: opts.corrKey } : {}),
      });

      const pending = s._consolePending;

      switch (type) {
        case "phase_change":
          // idle->turning 由 PROMPT received/AGENT started 表达,回 idle 由
          // PROMPT completed 表达——不重复入行。
          return {};
        case "agent_start":
          return row("AGENT", "meta-agent started");
        case "turn_start": {
          const index = typeof event.index === "number" ? event.index : 0;
          // turn 开始 = 模型请求即将发出(等待模型)。配对 turn_end 算时长。
          const next = row("TURN", `turn ${index + 1} started`, {
            corrKey: `turn:${index}`,
          });
          return {
            ...next,
            _consolePending: new Map(pending).set(`turn:${index}`, { ts: now }),
          };
        }
        case "message_start": {
          const mid = typeof event.message_id === "string" ? event.message_id : null;
          if (mid === null) return {};
          // message_start = 首 token 到达,"MODEL waiting" 配对出等待时长
          const waitStart = pending.get("model:waiting");
          const dur = waitStart ? now - waitStart.ts : null;
          const next = row("MODEL", "response started", {
            durationMs: dur,
            corrKey: `msg:${mid}`,
          });
          const np = new Map(pending);
          np.delete("model:waiting");
          np.set(`msg:${mid}`, { ts: now });
          // "chat" 活动行:等待模型 → 模型生成中(计时重置为生成段起点)。
          const act = s.execActivity[CHAT_ACTIVITY_SCOPE];
          if (act && (act.phase === "waiting_model" || act.phase === "compacting")) {
            return {
              ...next,
              _consolePending: np,
              execActivity: {
                ...s.execActivity,
                [CHAT_ACTIVITY_SCOPE]: { scope: "chat", phase: "model_generating", since: now, message: null },
              },
            };
          }
          return { ...next, _consolePending: np };
        }
        case "message_end": {
          const mid = typeof event.message_id === "string" ? event.message_id : null;
          if (mid === null) return {};
          const mStart = pending.get(`msg:${mid}`);
          const dur = mStart ? now - mStart.ts : null;
          const text = typeof event.text === "string" ? event.text : "";
          // 配对用完即删——长会话里 pending 表不随 message 数量增长
          if (!mStart) {
            return row("MODEL", `response complete`, { detail: text || null });
          }
          const np = new Map(pending);
          np.delete(`msg:${mid}`);
          const next = row("MODEL", `response complete`, {
            durationMs: dur,
            detail: text || null,
          });
          return { ...next, _consolePending: np };
        }
        case "tool_call_start": {
          const tid = typeof event.tool_use_id === "string" ? event.tool_use_id : null;
          const name = typeof event.tool_name === "string" ? event.tool_name : null;
          if (tid === null || name === null) return {};
          const next = row("TOOL", `${name} called`, { corrKey: tid });
          return {
            ...next,
            _consolePending: new Map(pending).set(tid, { ts: now }),
          };
        }
        case "tool_call_end": {
          const tid = typeof event.tool_use_id === "string" ? event.tool_use_id : null;
          if (tid === null) return {};
          const args = typeof event.args === "string"
            ? event.args
            : JSON.stringify(event.args ?? {});
          let detail: string | null = args;
          let preview = args;
          try {
            preview = JSON.stringify(JSON.parse(args), null, 2);
          } catch {
            // 非 JSON——原样展示
          }
          return row("TOOL", `args ${oneLine(preview, 80)}`, {
            detail: preview,
            corrKey: tid,
          });
        }
        case "tool_execution_start": {
          const tid = typeof event.tool_use_id === "string" ? event.tool_use_id : null;
          const name = typeof event.tool_name === "string" ? event.tool_name : null;
          if (tid === null) return {};
          const next = row("TOOL", `executing ${name ?? tid}`, { corrKey: `exec:${tid}` });
          return {
            ...next,
            _consolePending: new Map(pending).set(`exec:${tid}`, { ts: now }),
          };
        }
        case "tool_execution_end": {
          const tid = typeof event.tool_use_id === "string" ? event.tool_use_id : null;
          if (tid === null) return {};
          const execStart = pending.get(`exec:${tid}`);
          const dur = execStart ? now - execStart.ts : null;
          const ok = event.ok === true;
          let text = "";
          if (typeof event.result === "object" && event.result !== null) {
            const r = event.result as Record<string, unknown>;
            if (typeof r.text === "string") text = r.text;
          } else if (typeof event.result === "string") {
            text = event.result;
          }
          const err = typeof event.error === "string" ? event.error : null;
          const label = ok ? "completed" : "failed";
          const nameRow = row(
            "TOOL",
            `${label}${dur !== null ? ` (${dur}ms)` : ""}${ok ? "" : ": " + oneLine(err || text || "unknown error", 100)}`,
            {
              durationMs: dur,
              isError: !ok,
              detail: text || err || null,
              corrKey: `exec:${tid}`,
            }
          );
          const np = new Map(pending);
          np.delete(`exec:${tid}`);
          return {
            ...nameRow,
            _consolePending: np,
          };
        }
        case "savepoint": {
          const n = typeof event.entries_flushed === "number" ? event.entries_flushed : null;
          return row("SAVE", `savepoint${n !== null ? ` (${n} entries)` : ""}`);
        }
        case "compaction_start":
          return row("COMPACT", "compacting context");
        case "compaction_end": {
          // 压缩失败(如 no valid cut boundary)时 error 字段非空——必须
          // 以 ERROR 行呈现,不能误标"compaction done"。
          // 压缩失败 ⇒ 本次 run 必然失败(compaction_ops:错误只从失败路径
          // 发出)→ 立即结束挂着的 "chat" 活动计时,别让"等待模型响应"
          // 再挂两分钟等 prompt_terminal(权威 PROMPT failed 行仍由
          // prompt_terminal/prompt_state 补上)。
          const cerr = typeof event.error === "string" && event.error ? event.error : null;
          if (cerr) {
            const next = row("ERROR", `compaction failed: ${oneLine(cerr, 120)}`, {
              detail: cerr,
              isError: true,
            });
            const act = s.execActivity[CHAT_ACTIVITY_SCOPE];
            if (act && act.phase !== "done" && act.phase !== "error") {
              return {
                ...next,
                execActivity: {
                  ...s.execActivity,
                  [CHAT_ACTIVITY_SCOPE]: {
                    scope: "chat",
                    phase: "error",
                    since: act.since,
                    message: oneLine(cerr, 120),
                  },
                },
              };
            }
            return next;
          }
          return row("COMPACT", "compaction done");
        }
        case "tool_call_args_delta":
        case "message_update":
        case "thinking_delta":
        case "text_delta":
          // delta 级事件太吵;first-token 语义已由 message_start 承载,
          // thinking 不暴露。
          return {};
        case "turn_end": {
          const index = typeof event.index === "number" ? event.index : 0;
          const turnStart = pending.get(`turn:${index}`);
          const dur = turnStart ? now - turnStart.ts : null;
          const np = new Map(pending);
          np.delete(`turn:${index}`);
          const next = row("TURN", `turn ${index + 1} ended`, {
            durationMs: dur,
          });
          // "chat" 活动行:生成结束——若正在 model_generating/model_responding,
          // 切回 waiting_model(下一轮请求即将发出;没有下一轮则由终态收尾)。
          const act = s.execActivity[CHAT_ACTIVITY_SCOPE];
          if (act && (act.phase === "model_generating" || act.phase === "model_responding")) {
            return {
              ...next,
              _consolePending: np,
              execActivity: {
                ...s.execActivity,
                [CHAT_ACTIVITY_SCOPE]: { scope: "chat", phase: "waiting_model", since: now, message: null },
              },
            };
          }
          return { ...next, _consolePending: np };
        }
        case "prompt_terminal": {
          // 权威执行终态推送(后端线程分类,跨 run 投递到当前 socket)。
          // - 去重:同一 run 只允许一条终态行(corrKey = run:<id>)
          // - 归属:只有匹配 currentPromptRunId 的终态才清 prompt 计时器;
          //   旧 run 的终态照样追加到共享控制台(时间顺序即真实顺序)。
          const runId = typeof event.run_id === "string" ? event.run_id : null;
          const outcome = event.outcome;
          if (typeof outcome !== "string") return {};
          if (!["completed", "failed", "cancelled"].includes(outcome)) return {};
          const oc = outcome as "completed" | "failed" | "cancelled";
          const err = typeof event.error === "string" && event.error ? event.error : null;
          const reason = outcome === "failed" ? `run failed: ${err ?? "unknown"}` : outcome;
          return markConsoleTerminal(s, runId ?? null, oc, reason);
        }
        case "prompt_state": {
          // 重连对账:后端推送当前/最近一次 run 的状态。
          const run = event.run as Record<string, unknown> | undefined;
          if (!run || typeof run.run_id !== "string") return {};
          const runId = run.run_id;
          const status = run.status;
          if (status === "running") {
            // 执行仍在后台进行——不发明终态,只提示。
            return row("SYS", "连接已恢复,执行仍在后台运行");
          }
          const outcome = String(status);
          if (outcome !== "completed" && outcome !== "failed" && outcome !== "cancelled") return {};
          const reason = outcome === "failed" ? `run failed: ${String(run.error ?? "unknown")}` : outcome;
          return markConsoleTerminal(s, runId, outcome, reason);
        }
        case "spec_updated":
          return row("SPEC", "final spec updated");
        case "settled":
        case "agent_end":
          // settled 与 agent_end 表达同一事实——agent_end 后通常跟 settled,
          // 只记一条;若用户脚本只发 agent_end 也兼容。
          if (type === "settled") {
            const seen = s.consoleRows.some((r) => r.category === "AGENT" && r.text === "meta-agent finished");
            if (seen) return {};
            return row("AGENT", "meta-agent finished");
          }
          return {};
        case "error": {
          const msg = typeof event.message === "string" ? event.message : "unknown error";
          return row("ERROR", msg, { detail: msg, isError: true });
        }
        default:
          return {};
      }
    }),

  // 用户发送 prompt 时调用(ChatPanel.send)——控制台的起点。runId 由客户端
  // 生成，后端在 prompt_state/prompt_terminal 里回显，是终态行去重键。
  markConsolePromptStart: (text, runId) =>
    set((s) => {
      const next = appendConsole(s, {
        timestamp: Date.now(),
        category: "PROMPT",
        text: `received: ${oneLine(text, 120)}`,
        detail: text,
        durationMs: null,
        isError: false,
        corrKey: `run:${runId}`,
      });
      return {
        ...next,
        consolePromptStart: Date.now(),
        currentPromptRunId: runId,
        _consolePending: new Map(s._consolePending).set("model:waiting", { ts: Date.now() }),
      };
    }),

  // 终态(settled/error/断连)时调用——PROMPT completed/failed 带总耗时。
  // runId 传参时作为去重键：同一 run 的终态行只入一条（事件/推送/对账
  // 三条路径可能重复投递）。
  markConsolePromptEnd: (reason, isError = false, runId?: string) =>
    set((s) => {
      if (runId && s.consoleResolvedRunIds[`run:${runId}`]) {
        return {};
      }
      const start = s.consolePromptStart;
      const dur = start !== null ? Date.now() - start : null;
      const next = appendConsole(s, {
        timestamp: Date.now(),
        category: isError ? "ERROR" : "PROMPT",
        text: `${isError ? "aborted: " : "completed: "}${oneLine(reason, 120)}${start !== null ? ` (${(dur! / 1000).toFixed(1)}s)` : ""}`,
        detail: null,
        durationMs: dur,
        isError,
        ...(runId !== undefined ? { corrKey: `run:${runId}` } : {}),
      });
      const resolved =
        runId !== undefined
          ? { ...s.consoleResolvedRunIds, [`run:${runId}`]: true as const }
          : s.consoleResolvedRunIds;
      return {
        ...next,
        consoleResolvedRunIds: resolved,
        consolePromptStart: null,
        currentPromptRunId: null,
        _consolePending: new Map(),
      };
    }),
  // 失败/用户 Stop 时兜底:所有非终态的活动标成 error。与
  // finalizeInFlightExec 同一批触发点(见 ChatPanel 的事件分发)。
  finalizeInFlightActivity: (reason) =>
    set((s) => {
      const scopes = Object.keys(s.execActivity);
      let changed = false;
      const next: Record<string, ExecActivity> = { ...s.execActivity };
      for (const scope of scopes) {
        const cur = s.execActivity[scope];
        if (cur.phase === "done" || cur.phase === "error") continue;
        changed = true;
        next[scope] = { ...cur, phase: "error", message: cur.message ?? reason };
      }
      return changed ? { execActivity: next } : {};
    }),
}));
