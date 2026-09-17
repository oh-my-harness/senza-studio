// studio_frontend/src/store.exec.test.ts
// 执行可观测性 V1 的 store 行为测试。
import { describe, it, expect, beforeEach } from "vitest";
import { useStudioStore } from "./store";
import type { ExecRow, ExecToolRow } from "./types";
// 模拟后端转发的 Play 工具事件(字段与 senza-studio-runtime/play.py
// _run_agent_step 转发 + ws.py 原样转发保持一致)
function execEvent(
  type: string,
  stepId: string,
  toolUseId: string,
  extra: Record<string, unknown> = {}
): Record<string, unknown> {
  return { type, step_id: stepId, tool_use_id: toolUseId, ...extra };
}

const s = () => useStudioStore.getState();

describe("exec observability store", () => {
  beforeEach(() => {
    useStudioStore.getState().resetPlay();
  });

  it("happy path: calling -> executing -> done, args attached", () => {
    s().handleExecEvent(execEvent("tool_call_start", "step1", "tu_1", { name: "search" }));
    s().handleExecEvent(execEvent("tool_call_end", "step1", "tu_1", { args: '{"q":"abc"}' }));
    s().handleExecEvent(execEvent("tool_execution_start", "step1", "tu_1", { tool_name: "search" }));
    s().handleExecEvent(execEvent("tool_execution_end", "step1", "tu_1", { ok: true }));

    const rows = s().execRows;
    expect(rows.length).toBe(1);
    const row = rows[0];
    assertTool(row);
    expect(row.key).toBe("step1:tu_1");
    expect(row.toolName).toBe("search");
    expect(row.argsRaw).toBe('{"q":"abc"}');
    expect(row.phase).toBe("done");
    expect(row.ok).toBe(true);
    expect(row.error).toBeNull();
    expect(row.missingStart).toBe(false);
    expect(row.endedAt).not.toBeNull();
    expect(s().execIndex["step1:tu_1"]).toBe(row);
  });

  it("failed execution: ok=false marks phase failed with error", () => {
    s().handleExecEvent(execEvent("tool_call_start", "step1", "tu_1", { name: "mailer" }));
    s().handleExecEvent(execEvent("tool_execution_start", "step1", "tu_1", { tool_name: "mailer" }));
    s().handleExecEvent(
      execEvent("tool_execution_end", "step1", "tu_1", { ok: false, error: "SMTP down" })
    );

    const row = s().execIndex["step1:tu_1"];
    expect(row).toBeDefined();
    expect(row!.phase).toBe("failed");
    expect(row!.ok).toBe(false);
    expect(row!.error).toBe("SMTP down");
  });

  it("orphan execution_start synthesizes missing-start row", () => {
    s().handleExecEvent(execEvent("tool_execution_start", "step2", "tu_9", { tool_name: "grep" }));

    const rows = s().execRows;
    expect(rows.length).toBe(1);
    assertTool(rows[0]);
    expect(rows[0].missingStart).toBe(true);
    expect(rows[0].phase).toBe("executing");
    expect(rows[0].toolName).toBe("grep");
    expect(s().execIndex["step2:tu_9"]).toBe(rows[0]);

    // 后续 execution_end 照常落终态
    s().handleExecEvent(execEvent("tool_execution_end", "step2", "tu_9", { ok: true }));
    expect(s().execIndex["step2:tu_9"]!.phase).toBe("done");
  });

  it("orphan tool_call_end synthesizes missing-start executing row", () => {
    s().handleExecEvent(execEvent("tool_call_end", "step3", "tu_5", { args: '{"x":1}' }));

    const rows = s().execRows;
    expect(rows.length).toBe(1);
    assertTool(rows[0]);
    expect(rows[0].missingStart).toBe(true);
    expect(rows[0].phase).toBe("executing");
    expect(rows[0].argsRaw).toBe('{"x":1}');
    expect(rows[0].toolName).toBe("(未知工具)");
  });

  it("orphan execution_end synthesizes terminal row", () => {
    s().handleExecEvent(execEvent("tool_execution_end", "step4", "tu_7", { ok: true }));

    const rows = s().execRows;
    expect(rows.length).toBe(1);
    assertTool(rows[0]);
    expect(rows[0].missingStart).toBe(true);
    expect(rows[0].phase).toBe("done");
    expect(rows[0].endedAt).not.toBeNull();
  });

  it("turn_end inserts a turn marker", () => {
    s().handleExecEvent(execEvent("tool_call_start", "step1", "tu_1", { name: "search" }));
    s().handleExecEvent({ type: "turn_end", step_id: "step1", index: 0 });
    s().handleExecEvent({ type: "turn_end", step_id: "step1", index: 1 });

    const rows = s().execRows;
    expect(rows.length).toBe(3);
    expect(rows[1].kind).toBe("turn");
    expect(rows[2].kind).toBe("turn");
    if (rows[1].kind === "turn" && rows[2].kind === "turn") {
      expect(rows[1].index).toBe(0);
      expect(rows[2].index).toBe(1);
    }
    // turn 标记不进工具索引
    expect(Object.keys(s().execIndex)).toEqual(["step1:tu_1"]);
  });

  it("chat tool_call_start without step_id never enters exec state", () => {
    // 对话路径(meta-agent)的工具事件不带 step_id
    s().handleExecEvent({ type: "tool_call_start", tool_name: "web_search" });
    s().handleExecEvent({ type: "tool_call_start" });
    s().handleExecEvent({ type: "tool_call_end", tool_use_id: "tu_x" });

    expect(s().execRows.length).toBe(0);
    expect(s().execIndex).toEqual({});
  });

  it("finalizeInFlightExec marks in-flight rows failed, keeps terminal rows", () => {
    s().handleExecEvent(execEvent("tool_call_start", "step1", "tu_1", { name: "search" }));
    s().handleExecEvent(execEvent("tool_execution_start", "step1", "tu_2", { tool_name: "mailer" }));
    s().handleExecEvent(execEvent("tool_execution_end", "step1", "tu_3", { ok: true }));

    s().finalizeInFlightExec("用户停止运行");

    const calling = s().execIndex["step1:tu_1"]!;
    expect(calling.phase).toBe("failed");
    expect(calling.ok).toBe(false);
    expect(calling.error).toBe("用户停止运行");
    expect(calling.endedAt).not.toBeNull();

    const executing = s().execIndex["step1:tu_2"]!;
    expect(executing.phase).toBe("failed");
    expect(executing.error).toBe("用户停止运行");

    // 已落终态的不动
    expect(s().execIndex["step1:tu_3"]!.phase).toBe("done");

    // 幂等:再 finalize 一次不改变终态行
    s().finalizeInFlightExec("再次调用");
    expect(s().execIndex["step1:tu_1"]!.error).toBe("用户停止运行");
  });

  it("resetPlay clears exec state including index and seq", () => {
    s().handleExecEvent(execEvent("tool_call_start", "step1", "tu_1", { name: "search" }));
    s().handleExecEvent({ type: "turn_end", step_id: "step1", index: 0 });
    expect(s().execRows.length).toBe(2);

    s().resetPlay();

    expect(s().execRows).toEqual([]);
    expect(s().execIndex).toEqual({});
    expect(s().execSeq).toBe(1);

    // 重置后新一轮运行正常工作,不残留旧索引
    s().handleExecEvent(execEvent("tool_call_start", "step1", "tu_1", { name: "search" }));
    expect(s().execRows.length).toBe(1);
    expect(s().execIndex["step1:tu_1"]).toBeDefined();
  });

  it("row cap: rows trimmed to ~500 oldest-first, seq keeps growing, index pruned", () => {
    // 生成 505 个工具调用
    for (let i = 1; i <= 505; i++) {
      s().handleExecEvent(
        execEvent("tool_call_start", "step", `tu_${i}`, { name: `tool_${i}` })
      );
    }

    const rows = s().execRows;
    expect(rows.length).toBe(500);
    // 最老的 5 行被裁掉
    const first = rows[0];
    assertTool(first);
    expect(first.toolUseId).toBe("tu_6");
    const last = rows[rows.length - 1];
    assertTool(last);
    expect(last.toolUseId).toBe("tu_505");

    // seq 单调递增,不回退
    const seqs = rows.map((r) => r.seq);
    for (let i = 1; i < seqs.length; i++) {
      expect(seqs[i]).toBeGreaterThan(seqs[i - 1]);
    }
    expect(s().execSeq).toBe(506);

    // 索引:保留行的键还在且指向正确对象;被裁行的键已清掉
    expect(s().execIndex["step:tu_5"]).toBeUndefined();
    expect(s().execIndex["step:tu_6"]).toBe(rows[0]);
    expect(s().execIndex["step:tu_505"]).toBe(rows[rows.length - 1]);
    expect(Object.keys(s().execIndex).length).toBe(500);
  });

  it("trimmed rows stay consistent when later events reference them", () => {
    for (let i = 1; i <= 505; i++) {
      s().handleExecEvent(
        execEvent("tool_call_start", "step", `tu_${i}`, { name: `tool_${i}` })
      );
    }
    // 旧行的 execution_end 到了——行已被裁剪,索引里没有;不该抛错或重建
    expect(() => {
      s().handleExecEvent(execEvent("tool_execution_end", "step", "tu_1", { ok: true }));
    }).not.toThrow();
    // 孤儿 end 落为新行(missingStart),不复活被裁的行;追加后又触发一次
    // 裁剪,总数维持在 500
    expect(s().execRows.length).toBe(500);
    const orphan = s().execRows[s().execRows.length - 1];
    assertTool(orphan);
    expect(orphan.key).toBe("step:tu_1");
    expect(orphan.missingStart).toBe(true);
    expect(s().execIndex["step:tu_1"]).toBe(orphan);
  });

  it("defensive: malformed event fields never throw", () => {
    expect(() =>
      s().handleExecEvent({
        type: "tool_call_start",
        step_id: "step1",
        tool_use_id: "tu_1",
        name: 123, // 非字符串 name
      })
    ).not.toThrow();
    expect(s().execRows.length).toBe(0); // name 无效 -> 忽略事件

    expect(() =>
      s().handleExecEvent({ type: "tool_execution_end", step_id: "s", tool_use_id: "t", ok: "yes" })
    ).not.toThrow();
    // ok 非布尔 -> 视为成功结束(ok ?? false)
    expect(s().execIndex["s:t"]!.phase).toBe("done");
  });
});

function assertTool(row: ExecRow): asserts row is ExecToolRow {
  expect(row.kind).toBe("tool");
}
