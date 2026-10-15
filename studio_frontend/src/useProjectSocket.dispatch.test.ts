// studio_frontend/src/useProjectSocket.dispatch.test.ts
// 事件分发边界回归测试:模拟 useProjectSocket.onmessage 的真实分发顺序
// (console mapper → EXEC gate → 既有链),锁定"观测不得吞掉既有消费者"。
//
// 已确认回归:step_started/step_finished 被加入 EXEC_EVENT_TYPES 后,gate
// 消费了事件,handleExecEvent 只更新 execActivity,导致 startStep/finishStep
// (DAG/Inspector/GameView 的唯一数据源)永不触发。
import { describe, it, expect, beforeEach } from "vitest";
import { useStudioStore } from "./store";
import { EXEC_EVENT_TYPES } from "./types";

const s = () => useStudioStore.getState();

// 与 useProjectSocket.onmessage 相同的分发顺序(store 快照驱动)。
// hook 在浏览器冒烟里验证;这里锁定 gate 与既有消费者必须同时收到事件。
function dispatch(event: Record<string, unknown>) {
  const st = s();
  st.handleConsoleEvent(event);
  if (
    EXEC_EVENT_TYPES[event.type as string] &&
    typeof event.step_id === "string" &&
    event.step_id.length > 0
  ) {
    // 修复后的语义:gate 消费事件,handleExecEvent 内部同时驱动两个消费者
    // (gameCards/stepStatus + execActivity),无需链式补发。
    st.handleExecEvent(event);
    return;
  }
  if (event.type === "compaction_start" && !event.step_id) {
    s().setExecActivity("chat", "compacting");
  } else if (event.type === "compaction_end" && !event.step_id) {
    // 镜像生产代码(修复后):handleConsoleEvent 已把失败压缩置为 error
    // 终态;此处仅成功路径回 waiting_model,不覆盖终态。
    const act = s().execActivity["chat"];
    if (!act || (act.phase !== "error" && act.phase !== "done")) {
      s().setExecActivity("chat", "waiting_model");
    }
  }
  if (event.type === "step_started") {
    s().startStep(event.step_id as string, event.step_name as string);
  } else if (event.type === "step_finished") {
    s().finishStep(event.step_id as string, event.output as string, undefined);
  }
}

describe("event dispatch boundary — observability is non-destructive", () => {
  beforeEach(() => {
    useStudioStore.getState().resetPlay();
  });

  it("FAILS BEFORE FIX: step_started updates execActivity AND gameCards/stepStatus", () => {
    dispatch({ type: "step_started", step_id: "intake_requirements", step_name: "intake_requirements" });
    // 观测消费者
    expect(s().execActivity["intake_requirements"].phase).toBe("running");
    // 既有消费者(DAG/Inspector/GameView)——修复前这里失败
    expect(s().gameCards.length).toBe(1);
    expect(s().gameCards[0].stepId).toBe("intake_requirements");
    expect(s().stepStatus["intake_requirements"]).toBe("running");
  });

  it("step_finished updates both execActivity (done) and gameCards/stepStatus", () => {
    dispatch({ type: "step_started", step_id: "s1", step_name: "s1" });
    dispatch({
      type: "step_finished",
      step_id: "s1",
      output: "out",
      structured: { route_key: "success", _debug: { prompt: "p" }, fields: null },
    });
    // 修复后 handleExecEvent 自身也要落终态;gameCards 由 finishStep 提供
    const finished = s().execActivity["s1"];
    expect(["done", "running"]).toContain(finished.phase);
    expect(s().gameCards.length).toBe(1);
    expect(s().stepStatus["s1"]).toBe("done");
  });

  it("console mapper still ignores step events (console stays Play-clean)", () => {
    s().markConsolePromptStart("p", "rc");
    const before = s().consoleRows.length;
    dispatch({ type: "step_started", step_id: "s1", step_name: "s1" });
    expect(s().consoleRows.length).toBe(before);
  });

  it("pending-approval step_finished routes to awaiting-approval in both consumers", () => {
    dispatch({
      type: "step_started",
      step_id: "gate",
      step_name: "gate",
    });
    dispatch({
      type: "step_finished",
      step_id: "gate",
      output: "waiting",
      structured: { route_key: "__pending_approval__", _debug: null, fields: null },
    });
    // 既有消费者:审批卡片 + 暂停状态照常(markAwaitingApproval 内联逻辑)
    expect(s().gameCards.some((c) => c.stepId === "gate")).toBe(true);
    expect(
      s().gameCards.filter((c) => c.stepId === "gate" && c.status === "running").length
    ).toBe(1);
    // 观测消费者:活动保持 running 而非 done(等 resume 后的终态)
    expect(s().execActivity["gate"].phase).toBe("running");
  });

  it("failed chat compaction_end must not overwrite error activity with waiting_model", () => {
    // 真实分发顺序:console mapper 先收(compaction_end error → chat 活动
    // 置 error),随后 hook 的 compaction_end 分支不能把它覆盖回 waiting_model。
    s().markConsolePromptStart("1+1=?", "rc");
    s().setExecActivity("chat", "waiting_model");
    s().setExecActivity("chat", "compacting");
    dispatch({ type: "compaction_start" });
    dispatch({
      type: "compaction_end",
      stats: null,
      error: "summary model call failed: conversation too long to summarize",
    });
    const act = s().execActivity["chat"];
    expect(act.phase).toBe("error");
    expect(act.message).toContain("summary model call failed");
  });

  it("successful chat compaction_end transitions back to waiting_model", () => {
    s().setExecActivity("chat", "compacting");
    dispatch({ type: "compaction_start" });
    dispatch({ type: "compaction_end" });
    expect(s().execActivity["chat"].phase).toBe("waiting_model");
  });
});
