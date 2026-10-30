import { describe, expect, it, vi } from "vitest";

import { api, apiErrorMessage, apiErrorInfo } from "./api";
import {
  classifyWorkflowStopError,
  isNeutralStopOutcome,
  workflowStopNotice,
} from "./agentTeamWorkflowStop";

const STOPPED = {
  ok: true,
  workflow_id: "issue-42",
  phase: "escalated",
  terminal_reason: "operator requested workflow stop",
};

describe("workflow stop outcomes", () => {
  it("reports the authoritative terminal result and no resume", () => {
    const notice = workflowStopNotice({ kind: "stopped", result: STOPPED });
    expect(notice).toContain("issue-42");
    expect(notice).toContain("escalated");
    expect(notice).toContain("operator requested workflow stop");
    expect(notice).toContain("不能从原执行点恢复");
  });

  it("treats natural completion as neutral, not an error", () => {
    const outcome = classifyWorkflowStopError(
      new Error('409: {"ok":false,"error":"no running controlled workflow to stop"}')
    );
    expect(outcome).toEqual({ kind: "no-running" });
    expect(isNeutralStopOutcome(outcome)).toBe(true);
    expect(workflowStopNotice(outcome)).toContain("无需停止");
  });

  it("distinguishes an uncontrolled team", () => {
    const outcome = classifyWorkflowStopError(
      new Error(
        '409: {"ok":false,"error":"team is not a controlled workflow team"}'
      )
    );
    expect(outcome).toEqual({ kind: "uncontrolled" });
    expect(workflowStopNotice(outcome)).toContain("不是受控工作流团队");
  });

  it("treats an empty 404 as an older runtime without the stop route", () => {
    const outcome = classifyWorkflowStopError(new Error("404: "));
    expect(outcome).toEqual({ kind: "unsupported" });
    expect(workflowStopNotice(outcome)).toContain("不支持停止工作流");
  });

  it("distinguishes a deleted project from an unsupported runtime", () => {
    const outcome = classifyWorkflowStopError(
      new Error('404: {"ok":false,"error":"unknown project: team-1"}')
    );
    expect(outcome).toEqual({ kind: "missing" });
    expect(workflowStopNotice(outcome)).toContain("已不存在");
  });

  it("keeps proxy failures as errors", () => {
    const outcome = classifyWorkflowStopError(
      new Error('502: {"ok":false,"error":"Agent Team runtime unavailable"}')
    );
    expect(outcome).toEqual({
      kind: "failed",
      message: "Agent Team runtime unavailable",
    });
    expect(isNeutralStopOutcome(outcome)).toBe(false);
  });
});

describe("apiErrorInfo", () => {
  it("unwraps the runtime error field", () => {
    expect(
      apiErrorInfo(
        new Error('403: {"ok":false,"error":"workspace is not authorized"}')
      )
    ).toEqual({ status: 403, message: "workspace is not authorized" });
  });

  it("keeps non-JSON bodies and missing statuses", () => {
    expect(apiErrorInfo(new Error("404: Not Found"))).toEqual({
      status: 404,
      message: "Not Found",
    });
    expect(apiErrorInfo(new Error("boom"))).toEqual({
      status: null,
      message: "boom",
    });
    expect(apiErrorMessage(new Error("502: "))).toBe("HTTP 502");
  });
});

describe("stop capability probe", () => {
  it("treats 405 (route exists) as supported", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ status: 405 });
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.probeAgentTeamWorkflowStop()).resolves.toBe(true);
    vi.unstubAllGlobals();
  });

  it("treats 404 (older runtime) as unsupported", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ status: 404 });
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.probeAgentTeamWorkflowStop()).resolves.toBe(false);
    vi.unstubAllGlobals();
  });
});
