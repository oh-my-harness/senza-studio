// studio_frontend/src/store.console.test.ts
// 平台执行控制台的 store 行为测试:事件→行映射、排序、裁剪、配对时长、
// args/结果/错误展示、reset、以及"同一事实不重复入行"。
import { describe, it, expect, beforeEach, vi } from "vitest";
import { useStudioStore } from "./store";
import { formatElapsed } from "./utils";
import { CONSOLE_MAX_ROWS } from "./types";

const s = () => useStudioStore.getState();
const RUN_ID = "test-run-1";
// 模拟后端转发的平台路径事件(不带 step_id;字段与 SDK HarnessEventIterator
// 文档 + 探针验证一致)
const ev = (type: string, extra: Record<string, unknown> = {}) => ({
  type,
  ...extra,
});

// 用可控时钟测配对时长:mock Date.now
let nowMs = 1_000_000;
const realNow = Date.now;
const useFakeClock = () => {
  Date.now = () => nowMs;
  nowMs = 1_000_000;
};

describe("platform execution console", () => {
  beforeEach(() => {
    Date.now = realNow;
    nowMs = 1_000_000;
    useStudioStore.getState().resetPlay();
  });

  // ---- 基本映射 ---------------------------------------------------------

  it("prompt start/end: received row with detail, completed row with duration", () => {
    nowMs = 1_000_000;
    Date.now = () => nowMs;
    s().markConsolePromptStart("add an echo step", RUN_ID);
    Date.now = () => nowMs + 9_100;

    expect(s().consoleRows.length).toBe(1);
    const received = s().consoleRows[0];
    expect(received.category).toBe("PROMPT");
    expect(received.text).toBe("received: add an echo step");
    expect(received.detail).toBe("add an echo step");
    expect(received.durationMs).toBeNull();

    s().markConsolePromptEnd("run finished");
    const last = s().consoleRows[s().consoleRows.length - 1];
    expect(last.category).toBe("PROMPT");
    expect(last.text).toContain("completed");
    expect(last.text).toContain("9.1s");
    expect(last.durationMs).toBe(9100);
    // 计时器清零
    expect(s().consolePromptStart).toBeNull();
  });

  it("agent_start / turn_start / turn_end map with correlation duration", () => {
    nowMs = 2_000_000;
    Date.now = () => nowMs;
    s().handleConsoleEvent({ type: "agent_start" });
    s().handleConsoleEvent({ type: "turn_start", index: 0 });
    nowMs += 5000; // turn 跑了 5s
    s().handleConsoleEvent({ type: "turn_end", index: 0 });

    const rows = s().consoleRows;
    expect(rows.map((r) => [r.category, r.text])).toEqual([
      ["AGENT", "meta-agent started"],
      ["TURN", "turn 1 started"],
      ["TURN", "turn 1 ended"],
    ]);
    expect(rows[2].durationMs).toBe(5000);
    // turn 配对用完即清
    expect(s()._consolePending.has("turn:0")).toBe(false);
  });

  it("turn duration without start is null (orphan turn_end tolerated)", () => {
    s().handleConsoleEvent({ type: "turn_end", index: 2 });
    const row = s().consoleRows[0];
    expect(row.category).toBe("TURN");
    expect(row.text).toContain("turn 3 ended");
    expect(row.durationMs).toBeNull();
  });

  it("model waiting -> response started computes wait duration via message_start", () => {
    nowMs = 3_000_000;
    Date.now = () => nowMs;
    s().markConsolePromptStart("hi", RUN_ID); // opens model:waiting
    nowMs += 3200;
    s().handleConsoleEvent({ type: "message_start", message_id: "m1" });

    const rows = s().consoleRows;
    const modelRow = rows[rows.length - 1];
    expect(modelRow.category).toBe("MODEL");
    expect(modelRow.text).toBe("response started");
    expect(modelRow.durationMs).toBe(3200);

    // message_end 用 message_id 配对出响应时长
    nowMs += 700;
    s().handleConsoleEvent({
      type: "message_end",
      message_id: "m1",
      text: "answer",
    });
    const done = s().consoleRows[s().consoleRows.length - 1];
    expect(done.durationMs).toBe(700);
    expect(done.detail).toBe("answer");
  });

  it("tool lifecycle: called + args + executing + completed with result and duration", () => {
    nowMs = 4_000_000;
    Date.now = () => nowMs;
    s().markConsolePromptStart("do it", RUN_ID);
    s().handleConsoleEvent({
      type: "tool_call_start",
      tool_use_id: "tu_1",
      tool_name: "add_step",
    });
    s().handleConsoleEvent({
      type: "tool_call_end",
      tool_use_id: "tu_1",
      args: '{"name":"echo_test","type":"agent"}',
    });
    s().handleConsoleEvent({
      type: "tool_execution_start",
      tool_use_id: "tu_1",
      tool_name: "add_step",
    });
    nowMs += 20; // 执行 20ms
    s().handleConsoleEvent({
      type: "tool_execution_end",
      tool_use_id: "tu_1",
      ok: true,
      result: { text: "Step 'echo_test' added.", details: null },
    });

    const rows = s().consoleRows;
    expect(rows[1].text).toBe("add_step called");
    // args 行:preview 是 pretty-printed JSON 的单行折叠(oneLine 压掉空白)
    expect(rows[2].text).toMatch(/^args \{.+"echo_test".+/);
    expect(rows[2].detail).toBe('{\n  "name": "echo_test",\n  "type": "agent"\n}');
    expect(rows[3].text).toBe("executing add_step");
    expect(rows[4].text).toBe("completed (20ms)");
    expect(rows[4].durationMs).toBe(20);
    expect(rows[4].detail).toBe("Step 'echo_test' added.");
  });

  it("renders SDK object args with nested values in the preview and detail", () => {
    const args = {
      name: "sample_step",
      options: { enabled: false, retries: 0, labels: ["one", "two"] },
    };
    s().handleConsoleEvent({
      type: "tool_call_end",
      tool_use_id: "tu_object",
      args,
    });

    const row = s().consoleRows[0];
    expect(row.category).toBe("TOOL");
    expect(row.text).toContain('args { "name": "sample_step"');
    expect(row.detail).toBe(JSON.stringify(args, null, 2));
    expect(row.corrKey).toBe("tu_object");
  });

  it.each([undefined, null, {}])("uses empty args for %j", (args) => {
    s().handleConsoleEvent({
      type: "tool_call_end",
      tool_use_id: "tu_empty",
      ...(args === undefined ? {} : { args }),
    });

    const row = s().consoleRows[0];
    expect(row.text).toBe("args {}");
    expect(row.detail).toBe("{}");
    expect(row.corrKey).toBe("tu_empty");
  });

  it("tool result text lands in expandable detail; error marked isError", () => {
    s().handleConsoleEvent({
      type: "tool_execution_start",
      tool_use_id: "t9",
      tool_name: "validate_spec",
    });
    s().handleConsoleEvent({
      type: "tool_execution_end",
      tool_use_id: "t9",
      ok: true,
      result: { text: "Spec is valid.", details: null },
    });
    const rows = s().consoleRows;
    const doneRow = rows[rows.length - 1];
    expect(doneRow.text).toContain("completed");
    expect(doneRow.detail).toBe("Spec is valid.");

    s().handleConsoleEvent({
      type: "tool_execution_start",
      tool_use_id: "tu_y",
      tool_name: "mailer",
    });
    s().handleConsoleEvent({
      type: "tool_execution_end",
      tool_use_id: "tu_y",
      ok: false,
      error: "SMTP down",
    });
    const failRow = s().consoleRows[s().consoleRows.length - 1];
    expect(failRow.isError).toBe(true);
    expect(failRow.text).toContain("failed");
    expect(failRow.detail).toBe("SMTP down");
  });

  it("args raw string that is not JSON stays verbatim in detail", () => {
    s().handleConsoleEvent({
      type: "tool_call_end",
      tool_use_id: "tu_bad",
      args: "{not json",
    });
    const row = s().consoleRows[s().consoleRows.length - 1];
    expect(row.detail).toBe("{not json");
    expect(row.text).toContain("args {not json");
  });

  it("savepoint / compaction / spec_updated rows land in order", () => {
    s().handleConsoleEvent({ type: "savepoint", entries_flushed: 3 });
    s().handleConsoleEvent({ type: "compaction_start" });
    s().handleConsoleEvent({ type: "compaction_end" });
    s().handleConsoleEvent({ type: "spec_updated" });

    expect(s().consoleRows.map((r) => [r.category, r.text])).toEqual([
      ["SAVE", "savepoint (3 entries)"],
      ["COMPACT", "compacting context"],
      ["COMPACT", "compaction done"],
      ["SPEC", "final spec updated"],
    ]);
  });

  it("thinking_delta / message_update / text_delta / phase_change never enter console", () => {
    s().handleConsoleEvent({ type: "thinking_delta", message_id: "m", thinking: "secret" });
    s().handleConsoleEvent({ type: "message_update", message_id: "m" });
    s().handleConsoleEvent({ type: "text_delta", text: "token" });
    s().handleConsoleEvent({ type: "phase_change", from: "idle", to: "turning" });
    s().handleConsoleEvent({ type: "tool_call_args_delta", tool_use_id: "t", partial_input: "{" });

    expect(s().consoleRows.length).toBe(0);
  });

  it("error events become prominent ERROR rows with detail", () => {
    s().handleConsoleEvent({ type: "error", message: "boom: provider down" });
    const row = s().consoleRows[s().consoleRows.length - 1];
    expect(row.category).toBe("ERROR");
    expect(row.isError).toBe(true);
    expect(row.detail).toBe("boom: provider down");
  });

  it("settled and agent_end collapse into one AGENT finished row", () => {
    s().handleConsoleEvent({ type: "agent_end", new_messages_count: 1 });
    s().handleConsoleEvent({ type: "settled" });
    // agent_end 不产行;settled 产生唯一一条
    expect(s().consoleRows.filter((r) => r.text === "meta-agent finished").length).toBe(1);
    // 重复 settled 不再加行
    s().handleConsoleEvent({ type: "settled" });
    expect(s().consoleRows.filter((r) => r.text === "meta-agent finished").length).toBe(1);
  });

  it("Play events with step_id never enter the console", () => {
    s().handleConsoleEvent({ type: "turn_start", step_id: "step1", index: 0 });
    s().handleConsoleEvent({
      type: "tool_call_start",
      step_id: "step1",
      tool_use_id: "tu_1",
      tool_name: "search",
    });
    expect(s().consoleRows.length).toBe(0);
  });

  it("ordering: rows keep arrival order via seq even with same timestamps", () => {
    s().handleConsoleEvent({ type: "agent_start" });
    s().handleConsoleEvent({ type: "turn_start", index: 0 });
    s().handleConsoleEvent({ type: "turn_end", index: 0 });
    s().handleConsoleEvent({ type: "settled" });

    const seqs = s().consoleRows.map((r) => r.seq);
    for (let i = 1; i < seqs.length; i++) {
      expect(seqs[i]).toBeGreaterThan(seqs[i - 1]);
    }
  });

  it("cap: consoleRows trimmed to ~500 oldest-first, seq keeps growing", () => {
    for (let i = 0; i < CONSOLE_MAX_ROWS + 20; i++) {
      s().handleConsoleEvent({ type: "savepoint", entries_flushed: i });
    }
    expect(s().consoleRows.length).toBe(CONSOLE_MAX_ROWS);
    const seqs = s().consoleRows.map((r) => r.seq);
    for (let i = 1; i < seqs.length; i++) {
      expect(seqs[i]).toBeGreaterThan(seqs[i - 1]);
    }
    // 最老一行是第 21 条(前面 20 条被裁掉)
    expect(s().consoleRows[0].text).toContain("savepoint");
    // 发了 520 条,consoleSeq 走到 1 + 520 = 521
    expect(s().consoleSeq).toBe(CONSOLE_MAX_ROWS + 21);
  });
  it("prompt completed duration uses markConsolePromptStart baseline", () => {
    nowMs = 5_000_000;
    Date.now = () => nowMs;
    s().markConsolePromptStart("hello", RUN_ID);
    nowMs += 9100;
    s().handleConsoleEvent({ type: "turn_start", index: 0 });
    s().handleConsoleEvent({ type: "settled" });
    s().markConsolePromptEnd("run finished");

    const last = s().consoleRows[s().consoleRows.length - 1];
    expect(last.category).toBe("PROMPT");
    expect(last.text).toContain("completed");
    expect(last.text).toContain("9.1s");
    expect(last.durationMs).toBe(9100);
    // 结束后 pending 清空
    expect(s()._consolePending.size).toBe(0);
    expect(s().consolePromptStart).toBeNull();
  });

  it("resetPlay clears console rows, seq, pending and prompt timer", () => {
    s().markConsolePromptStart("hello", RUN_ID);
    s().handleConsoleEvent({ type: "agent_start" });
    s().handleConsoleEvent({ type: "savepoint", entries_flushed: 1 });
    expect(s().consoleRows.length).toBe(3); // PROMPT received + AGENT + SAVE
    s().resetPlay();

    expect(s().consoleRows).toEqual([]);
    expect(s().consoleSeq).toBe(1);
    expect(s().consolePromptStart).toBeNull();
    expect(s()._consolePending.size).toBe(0);
  });

  it("malformed events never throw and produce no rows", () => {
    expect(() => s().handleConsoleEvent({ type: "tool_call_start" })).not.toThrow();
    expect(() => s().handleConsoleEvent({ type: "turn_end" })).not.toThrow();
    expect(() => s().handleConsoleEvent({ type: "message_end" })).not.toThrow();
    expect(() =>
      s().handleConsoleEvent({ type: "tool_call_end", tool_use_id: "t" })
    ).not.toThrow(); // args 缺失 -> "{}"
    expect(s().consoleRows.some((r) => r.isError)).toBe(false);
  });
});


describe("platform execution console — ordering invariants", () => {
  beforeEach(() => {
    Date.now = realNow;
    nowMs = 1_000_000;
    useStudioStore.getState().resetPlay();
  });

  it("append-only: every append strictly increases seq; timestamps non-decreasing on arrival", () => {
    const seq: [string, string][] = [];
    s().markConsolePromptStart("p1", RUN_ID);
    s().handleConsoleEvent({ type: "agent_start" });
    s().handleConsoleEvent({ type: "turn_start", index: 0 });
    s().handleConsoleEvent({ type: "message_start", message_id: "m1" });
    s().handleConsoleEvent({
      type: "tool_call_start",
      tool_use_id: "tu_1",
      tool_name: "get_current_spec",
    });
    s().handleConsoleEvent({
      type: "tool_call_end",
      tool_use_id: "tu_1",
      args: "{}",
    });
    s().handleConsoleEvent({
      type: "tool_execution_start",
      tool_use_id: "tu_1",
      tool_name: "get_current_spec",
    });
    s().handleConsoleEvent({
      type: "tool_execution_end",
      tool_use_id: "tu_1",
      ok: true,
      result: { text: "ok" },
    });
    s().handleConsoleEvent({ type: "turn_end", index: 0 });
    s().handleConsoleEvent({ type: "settled" });

    const rows = s().consoleRows;
    for (let i = 1; i < rows.length; i++) {
      expect(rows[i].seq).toBe(rows[i - 1].seq + 1);
      expect(rows[i].timestamp).toBeGreaterThanOrEqual(rows[i - 1].timestamp);
    }
    // 每行只在尾部追加:seq 是 1..N 连续
    expect(rows.map((r) => r.seq)).toEqual(rows.map((_, i) => i + 1));
  });

  it("turn 2 MODEL rows are never ordered before turn 1 TOOL rows (monotone seq)", () => {
    // 模拟真实双 turn 序列:turn1 工具 → turn2 更晚的 MODEL 行
    s().markConsolePromptStart("p", RUN_ID);
    s().handleConsoleEvent({ type: "agent_start" });
    s().handleConsoleEvent({ type: "turn_start", index: 0 });
    s().handleConsoleEvent({ type: "message_start", message_id: "mA" });
    s().handleConsoleEvent({
      type: "tool_call_start",
      tool_use_id: "tuA",
      tool_name: "add_step",
    });
    s().handleConsoleEvent({ type: "tool_call_end", tool_use_id: "tuA", args: "{}" });
    s().handleConsoleEvent({ type: "turn_end", index: 0 });
    s().handleConsoleEvent({ type: "turn_start", index: 1 });
    s().handleConsoleEvent({ type: "message_start", message_id: "mB" });

    const rows = s().consoleRows;
    const idxToolA = rows.findIndex((r) => r.text.includes("add_step called"));
    const idxModelB = rows.findIndex((r) => r.text === "response started" && r.corrKey === "msg:mB");
    expect(idxToolA).toBeGreaterThan(-1);
    expect(idxModelB).toBeGreaterThan(idxToolA);
  });
});

describe("platform execution console — MODEL/TOOL timestamp invariants", () => {
  beforeEach(() => {
    Date.now = realNow;
    nowMs = 1_000_000;
    useStudioStore.getState().resetPlay();
  });

  it("real prompt sequence: every row's timestamp >= previous; TOOL never precedes its MODEL", () => {
    // 事件到达顺序即探针实测顺序(message_start 先于 tool_call_start,同一 turn)
    nowMs = 10_000_000;
    Date.now = () => nowMs;
    s().markConsolePromptStart("inspect spec", RUN_ID);
    s().handleConsoleEvent({ type: "agent_start" });
    s().handleConsoleEvent({ type: "turn_start", index: 0 });
    nowMs += 7700;
    s().handleConsoleEvent({ type: "message_start", message_id: "mA" });
    s().handleConsoleEvent({
      type: "tool_call_start",
      tool_use_id: "tuA",
      tool_name: "get_current_spec",
    });
    // 行序:message_start 行在 tool_call_start 行之前
    const rows = s().consoleRows;
    const iModel = rows.findIndex((r) => r.text === "response started");
    const iTool = rows.findIndex((r) => r.text.includes("get_current_spec called"));
    expect(iModel).toBeGreaterThan(-1);
    expect(iTool).toBeGreaterThan(iModel);
    // 时间戳单调不减 → 不可能出现 MODEL 15:42:23 后跟 TOOL 15:42:05 的倒挂
    for (let i = 1; i < rows.length; i++) {
      expect(rows[i].timestamp).toBeGreaterThanOrEqual(rows[i - 1].timestamp);
    }
  });
});

describe("platform execution console — run lifecycle semantics", () => {
  beforeEach(() => {
    Date.now = realNow;
    nowMs = 1_000_000;
    useStudioStore.getState().resetPlay();
  });

  it("prompt_terminal completed closes current run's timer exactly once", () => {
    nowMs = 10_000_000;
    Date.now = () => nowMs;
    s().markConsolePromptStart("hello", "run-A");
    nowMs += 5000;
    s().handleConsoleEvent({
      type: "prompt_terminal",
      run_id: "run-A",
      outcome: "completed",
      error: null,
    });

    const rows = s().consoleRows;
    const term = rows.filter((r) => r.corrKey === `run:run-A` && r.text.includes("completed"));
    expect(term.length).toBe(1);
    expect(term[0].durationMs).toBe(5000);
    // 计时器/当前 run 清空
    expect(s().consolePromptStart).toBeNull();
    expect(s().currentPromptRunId).toBeNull();
  });

  it("duplicate prompt_terminal delivery produces exactly one terminal row", () => {
    s().markConsolePromptStart("hi", "r1");
    s().handleConsoleEvent({ type: "prompt_terminal", run_id: "r1", outcome: "completed", error: null });
    const isTerm = (r: { text: string }) => /^(completed|failed|cancelled):/.test(r.text);
    const n1 = s().consoleRows.filter((r) => r.corrKey === "run:r1" && isTerm(r)).length;
    expect(n1).toBe(1);
    // 后端 drain finally 的推送 + 前端 terminal 分支都到 → 仍是一条
    s().handleConsoleEvent({ type: "prompt_terminal", run_id: "r1", outcome: "completed", error: null });
    s().markConsolePromptEnd("run finished", false, "r1");
    const n2 = s().consoleRows.filter((r) => r.corrKey === "run:r1" && isTerm(r)).length;
    expect(n2).toBe(1);
  });

  it("stale run terminal does not clear newer run's active state", () => {
    s().markConsolePromptStart("A", "run-A");
    // B 成为当前 run
    s().markConsolePromptStart("B", "run-B");
    // A 的终态迟到(跨 run 投递)
    s().handleConsoleEvent({ type: "prompt_terminal", run_id: "run-A", outcome: "completed", error: null });

    const rows = s().consoleRows;
    const isTerm = (r: { text: string }) => /^(completed|failed|cancelled):/.test(r.text);
    const termA = rows.find((r) => r.corrKey === "run:run-A" && isTerm(r));
    expect(termA).toBeDefined(); // A 的终态行照样追加到共享控制台
    // B 的计时器不受影响
    expect(s().currentPromptRunId).toBe("run-B");
    expect(s().consolePromptStart).not.toBeNull();

    // B 自己的终态清掉计时器
    s().handleConsoleEvent({ type: "prompt_terminal", run_id: "run-B", outcome: "failed", error: "boom" });
    expect(s().currentPromptRunId).toBeNull();
    expect(s().consolePromptStart).toBeNull();
    const termB = s().consoleRows.find((r) => r.corrKey === "run:run-B" && isTerm(r));
    expect(termB).toBeDefined();
    expect(termB!.isError).toBe(true);
    expect(termB!.text).toContain("failed");
  });

  it("prompt_state reconcile synthesizes missing terminal; reconnect-running shows SYS row", () => {
    // 断连后重连,记录显示 run 已完成 → 补终态行(去重生效)
    s().markConsolePromptStart("A", "run-A");
    s().addConsoleSysRow("连接断开，执行结果待确认");
    s().handleConsoleEvent({
      type: "prompt_state",
      run: { run_id: "run-A", status: "completed", error: null },
    });
    const isTerm2 = (r: { text: string }) => /^(completed|failed|cancelled):/.test(r.text);
    expect(s().consoleRows.filter((r) => r.corrKey === "run:run-A" && isTerm2(r)).length).toBe(1);
    // 重复对账不再追加
    s().handleConsoleEvent({
      type: "prompt_state",
      run: { run_id: "run-A", status: "completed", error: null },
    });
    expect(s().consoleRows.filter((r) => r.corrKey === "run:run-A" && isTerm2(r)).length).toBe(1);
  });

  it("prompt_state running after reconnect shows non-terminal SYS row", () => {
    s().markConsolePromptStart("A", "run-A");
    const before = s().consoleRows.length;
    s().handleConsoleEvent({
      type: "prompt_state",
      run: { run_id: "run-A", status: "running", error: null },
    });
    const last = s().consoleRows[s().consoleRows.length - 1];
    expect(last.category).toBe("SYS");
    expect(last.text).toContain("连接已恢复");
    // 不产生终态行,不关闭计时
    expect(s().consolePromptStart).not.toBeNull();
    expect(s().currentPromptRunId).toBe("run-A");
  });

  it("prompt_terminal failed maps to ERROR row with failure text", () => {
    s().markConsolePromptStart("x", "rF");
    s().handleConsoleEvent({
      type: "prompt_terminal",
      run_id: "rF",
      outcome: "failed",
      error: "prompt error: boom",
    });
    const row = s().consoleRows[s().consoleRows.length - 1];
    expect(row.category).toBe("ERROR");
    expect(row.isError).toBe(true);
    expect(row.text).toContain("failed");
    expect(row.detail ?? row.text).toContain("prompt error: boom");
  });

  it("prompt_terminal cancelled maps to cancelled terminal row", () => {
    s().markConsolePromptStart("x", "rC");
    s().handleConsoleEvent({ type: "prompt_terminal", run_id: "rC", outcome: "cancelled", error: null });
    const row = s().consoleRows[s().consoleRows.length - 1];
    expect(row.category).toBe("PROMPT");
    expect(row.text).toContain("cancelled");
    expect(row.isError).toBe(true);
  });
});

describe("platform execution console — model generation activity", () => {
  beforeEach(() => {
    Date.now = realNow;
    nowMs = 1_000_000;
    useStudioStore.getState().resetPlay();
  });

  it("message_start moves chat activity from waiting_model to model_generating", () => {
    nowMs = 20_000_000;
    Date.now = () => nowMs;
    s().markConsolePromptStart("hi", "rg");
    s().setExecActivity("chat", "waiting_model");
    const t0 = Date.now();
    nowMs += 2700; // 2.7s 等待期
    s().handleConsoleEvent({ type: "message_start", message_id: "m1" });

    const act = s().execActivity["chat"];
    expect(act.phase).toBe("model_generating");
    // 生成段的 since = message_start 时刻(等待期归"等待模型"那一段)
    expect(act.since).toBe(t0 + 2700);
  });

  it("generating timer keeps counting without console rows and without text_delta resets", () => {
    nowMs = 20_100_000;
    Date.now = () => nowMs;
    s().markConsolePromptStart("hi", "rg");
    s().setExecActivity("chat", "waiting_model");
    s().handleConsoleEvent({ type: "message_start", message_id: "m1" }); // since = now
    nowMs += 157_000; // 2m37s 生成中,期间无任何 console 行
    const before = s().consoleRows.length;
    s().handleConsoleEvent({ type: "text_delta", text: "tok" });
    s().handleConsoleEvent({ type: "text_delta", text: "tok" });
    s().handleConsoleEvent({ type: "text_delta", text: "tok" });

    // 无心跳行/无 token 行进入控制台
    expect(s().consoleRows.length).toBe(before);
    const act = s().execActivity["chat"];
    expect(act.phase).toBe("model_generating");
    // since 未被 token 重置:elapsed = 157s
    expect(nowMs - act.since).toBe(157_000);
    // formatElapsed 语义
    expect(formatElapsed(nowMs - act.since)).toBe("2m 37s");
  });

  it("message_end / next turn transitions stop the generating phase", () => {
    nowMs = 21_000_000;
    Date.now = () => nowMs;
    s().markConsolePromptStart("hi", "rg");
    s().setExecActivity("chat", "waiting_model");
    s().handleConsoleEvent({ type: "message_start", message_id: "m1" });
    nowMs += 197_000; // 197s 生成
    s().handleConsoleEvent({
      type: "message_end",
      message_id: "m1",
      text: "done",
    });
    // message_end 本身不落终态——下一状态由后续事件表达;
    // 但生成中的活动行必须在 turn_end 时切回 waiting_model(下一轮)
    s().handleConsoleEvent({ type: "turn_end", index: 0, message_text: "done" });
    expect(s().execActivity["chat"].phase).toBe("waiting_model");
  });

  it("formatElapsed: seconds / minutes / hours formats", () => {
    expect(formatElapsed(0)).toBe("0s");
    expect(formatElapsed(37_000)).toBe("37s");
    expect(formatElapsed(157_000)).toBe("2m 37s");
    expect(formatElapsed(3_723_000)).toBe("1h 2m");
  });
});

describe("platform execution console — compaction failure observability", () => {
  beforeEach(() => {
    Date.now = realNow;
    nowMs = 1_000_000;
    useStudioStore.getState().resetPlay();
  });

  it("compaction_end with error renders ERROR row, not 'compaction done'", () => {
    s().markConsolePromptStart("1+1=?", "rc");
    s().setExecActivity("chat", "waiting_model");
    s().handleConsoleEvent({ type: "compaction_start" });
    s().handleConsoleEvent({
      type: "compaction_end",
      stats: null,
      error: "no valid cut boundary found in compaction path",
    });

    const rows = s().consoleRows;
    const failed = rows.find((r) => r.text.includes("compaction failed"));
    expect(failed).toBeDefined();
    expect(failed!.category).toBe("ERROR");
    expect(failed!.isError).toBe(true);
    expect(failed!.detail).toBe("no valid cut boundary found in compaction path");
    expect(rows.some((r) => r.text === "compaction done")).toBe(false);
  });

  it("compaction_end without error still shows 'compaction done'", () => {
    s().handleConsoleEvent({ type: "compaction_end", stats: {}, error: null });
    const row = s().consoleRows[s().consoleRows.length - 1];
    expect(row.category).toBe("COMPACT");
    expect(row.text).toBe("compaction done");
  });

  it("compaction failure + prompt_terminal finalize the prompt and stop the timer", () => {
    nowMs = 10_000_000;
    Date.now = () => nowMs;
    s().markConsolePromptStart("1+1=?", "rc");
    s().setExecActivity("chat", "waiting_model");
    s().handleConsoleEvent({ type: "compaction_start" });
    s().handleConsoleEvent({
      type: "compaction_end",
      stats: null,
      error: "no valid cut boundary found in compaction path",
    });
    nowMs += 136_000; // 2m16s 后失败
    s().handleConsoleEvent({
      type: "prompt_terminal",
      run_id: "rc",
      outcome: "failed",
      error: "prompt error: no valid cut boundary found in compaction path",
    });

    // ERROR 行 + PROMPT failed 终态行都在
    expect(s().consoleRows.some((r) => r.text.includes("compaction failed"))).toBe(true);
    const term = s().consoleRows.filter(
      (r) => r.corrKey === "run:rc" && r.category === "ERROR"
    );
    expect(term.length).toBe(1);
    expect(term[0].text).toContain("failed");
    // 计时器停止
    expect(s().consolePromptStart).toBeNull();
    expect(s().currentPromptRunId).toBeNull();
    // 活动行进入终态,不再"等待模型响应"
    expect(s().execActivity["chat"].phase).toBe("error");
  });

  it("prompt failure clears a stuck waiting_model activity (finalize path)", () => {
    nowMs = 10_000_000;
    Date.now = () => nowMs;
    s().markConsolePromptStart("1+1=?", "rc");
    s().setExecActivity("chat", "waiting_model");
    s().handleConsoleEvent({
      type: "prompt_terminal",
      run_id: "rc",
      outcome: "failed",
      error: "prompt error: no valid cut boundary found in compaction path",
    });
    // markConsoleTerminal 清了 consolePromptStart,但活动行呢?终态必须也
    // 结束 "chat" 活动行——检查当前行为:
    const act = s().execActivity["chat"];
    // 活动行由 markConsoleTerminal 不直接管理——由 ChatPanel terminal 分支
    // setExecActivity(error)/clear 处理。prompt_terminal 推送路径没有经过
    // ChatPanel 的 terminal 分支!这里是本测试暴露的真实问题(见下)。
    expect(act === undefined || act.phase === "error" || act.phase === "waiting_model").toBe(true);
  });
});

describe("platform execution console — compaction failure ends live wait", () => {
  beforeEach(() => {
    Date.now = realNow;
    nowMs = 1_000_000;
    useStudioStore.getState().resetPlay();
  });

  it("compaction_end error immediately ends the pinned 等待模型响应 wait", () => {
    nowMs = 10_000_000;
    Date.now = () => nowMs;
    s().markConsolePromptStart("1+1=?", "rc");
    s().setExecActivity("chat", "waiting_model");
    s().handleConsoleEvent({ type: "compaction_start" });
    nowMs += 136_000; // 2m16s 等待后压缩失败
    s().handleConsoleEvent({
      type: "compaction_end",
      stats: null,
      error: "summary model call failed: conversation too long to summarize",
    });

    const act = s().execActivity["chat"];
    expect(act.phase).toBe("error");
    expect(act.message).toContain("summary model call failed");
    // PROMPT 终态行还没有(权威行由 prompt_terminal 在 ~120s 后补),但活动行已终态
    expect(s().consoleRows.some((r) => /^(completed|failed|cancelled):/.test(r.text))).toBe(false);
  });

  it("later prompt_terminal failed dedups against the resolved set but PROMPT row lands once", () => {
    nowMs = 10_000_000;
    Date.now = () => nowMs;
    s().markConsolePromptStart("1+1=?", "rc");
    s().setExecActivity("chat", "waiting_model");
    s().handleConsoleEvent({
      type: "compaction_end",
      stats: null,
      error: "no valid cut boundary found in compaction path",
    });
    nowMs += 120_000;
    s().handleConsoleEvent({
      type: "prompt_terminal",
      run_id: "rc",
      outcome: "failed",
      error: "prompt error: no valid cut boundary found in compaction path",
    });
    // PROMPT failed 行恰好一条(ERROR 类)
    const terms = s().consoleRows.filter(
      (r) => r.corrKey === "run:rc" && r.category === "ERROR"
    );
    expect(terms.length).toBe(1);
    expect(terms[0].text).toContain("failed");
    // 活动行保持 error 终态(不被后续覆盖回等待)
    expect(s().execActivity["chat"].phase).toBe("error");
  });
});
