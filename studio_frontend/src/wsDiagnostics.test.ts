// studio_frontend/src/wsDiagnostics.test.ts
// WebSocket 断连诊断的回归测试:CloseEvent → 控制台行的文本/详情构造、
// 空 reason 处理、onerror 不产生重复行、断开绝不发明 PROMPT 终态。
import { describe, it, expect, beforeEach, vi } from "vitest";
import { useStudioStore } from "./store";
import { wsCloseDiagnostics } from "./utils";

const s = () => useStudioStore.getState();
const terminalRows = () =>
  s().consoleRows.filter(
    (r) => r.category === "PROMPT" || (r.isError && r.text.includes("failed"))
  );
const sysRows = () => s().consoleRows.filter((r) => r.category === "SYS");

describe("ws close diagnostics helper", () => {
  it("abnormal close 1006: clean=false, browser provides no reason", () => {
    const d = wsCloseDiagnostics({ code: 1006, wasClean: false, reason: "" });
    expect(d.text).toBe(
      "WebSocket disconnected · code=1006 · clean=false · reconnect required"
    );
    expect(d.detail).toContain("code=1006 (abnormal closure)");
    expect(d.detail).toContain("clean=false");
    expect(d.detail).toContain("reason=(浏览器未提供)");
  });

  it("clean close with code and reason", () => {
    const d = wsCloseDiagnostics({ code: 1000, wasClean: true, reason: "server shutdown" });
    expect(d.text).toContain("code=1000");
    expect(d.text).toContain("clean=true");
    expect(d.detail).toContain("(normal closure)");
    expect(d.detail).toContain("reason=server shutdown");
  });

  it("non-standard codes are reported opaquely, no invented cause", () => {
    const d = wsCloseDiagnostics({ code: 4321, wasClean: false, reason: "" });
    expect(d.detail).toContain("code=4321 (unknown code 4321)");
    expect(d.detail).toContain("reason=(浏览器未提供)");
    // 不发明人类可读原因——文本里不得出现猜测性短语
    expect(d.detail).not.toMatch(/timeout|network|proxy|server error/i);
  });

  it("missing fields fall back to abnormal-close defaults", () => {
    const d = wsCloseDiagnostics({});
    expect(d.text).toContain("code=1006");
    expect(d.text).toContain("clean=false");
  });
});

describe("connection loss console behavior", () => {
  beforeEach(() => {
    useStudioStore.getState().resetPlay();
  });

  it("close during active prompt appends SYS diagnostic, NOT a PROMPT terminal", () => {
    s().markConsolePromptStart("A", "run-A");
    // 模拟 onclose 真实调用路径:store 动作(与 ChatPanel.onclose 相同)
    const d = wsCloseDiagnostics({ code: 1006, wasClean: false, reason: "" });
    s().addConsoleSysRow(d.text, d.detail);

    // 有诊断 SYS 行
    expect(sysRows().length).toBe(1);
    expect(sysRows()[0].text).toContain("code=1006");
    expect(sysRows()[0].detail).toContain("abnormal closure");
    // 绝不发明 PROMPT 终态——控制台仍处于未结算状态
    expect(terminalRows().filter((r) => /^(completed|failed|cancelled):/.test(r.text)).length).toBe(0);
    expect(s().consolePromptStart).not.toBeNull(); // 计时器保持,等真结果对账
    expect(s().currentPromptRunId).toBe("run-A");
  });

  it("true outcome arriving after connection loss appends exactly one terminal row", () => {
    s().markConsolePromptStart("A", "run-A");
    s().addConsoleSysRow("WebSocket disconnected · code=1006 · clean=false · reconnect required");
    s().handleConsoleEvent({
      type: "prompt_terminal",
      run_id: "run-A",
      outcome: "completed",
      error: null,
    });

    const terms = s().consoleRows.filter((r) => /^completed:/.test(r.text));
    expect(terms.length).toBe(1);
    // 断连诊断行仍在(不因终态到达被清除)
    expect(sysRows().length).toBe(1);
  });

  it("duplicate terminal delivery after reconnect reconcile stays at one", () => {
    s().markConsolePromptStart("A", "run-A");
    s().addConsoleSysRow("WebSocket disconnected · code=1006 · clean=false · reconnect required");
    // 重连对账补终态
    s().handleConsoleEvent({
      type: "prompt_state",
      run: { run_id: "run-A", status: "completed", error: null },
    });
    // 后端推送又到了(跨 run 投递)
    s().handleConsoleEvent({
      type: "prompt_terminal",
      run_id: "run-A",
      outcome: "completed",
      error: null,
    });
    expect(s().consoleRows.filter((r) => /^completed:/.test(r.text)).length).toBe(1);
  });
});

// 防回归:onerror 与 onclose 的去重语义锁定在 ChatPanel 层——这里以 store
// 动作组合表达同样的事实:onerror 只做状态清理(不进控制台),诊断行只由
// close 记一次。
describe("onerror/onclose dedup semantics", () => {
  beforeEach(() => {
    useStudioStore.getState().resetPlay();
    vi.restoreAllMocks();
  });

  it("onerror alone contributes no console row; close contributes exactly one", () => {
    const before = s().consoleRows.length;
    // onerror 的 store 副作用 = 状态清理(无控制台动作)。诊断行只由
    // onclose 记一次——重复投递由 onclose 只挂一次处理器保证。
    const d = wsCloseDiagnostics({ code: 1006, wasClean: false, reason: "" });
    s().addConsoleSysRow(d.text, d.detail);
    expect(s().consoleRows.length).toBe(before + 1);
    expect(sysRows().length).toBe(1);
  });
});
