import { describe, expect, it, vi } from "vitest";

import { api, apiErrorMessage, apiErrorInfo } from "./api";
import {
  classifyWorkflowStopError,
  isNeutralStopOutcome,
  workflowStopControl,
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

  it("keeps an unrecognized 409 a failure and preserves the runtime reason", () => {
    const outcome = classifyWorkflowStopError(
      new Error('409: {"ok":false,"error":"workflow is only partially escalated"}')
    );
    expect(outcome).toEqual({
      kind: "failed",
      message: "workflow is only partially escalated",
    });
    expect(isNeutralStopOutcome(outcome)).toBe(false);
    expect(workflowStopNotice(outcome)).toBe(
      "workflow is only partially escalated"
    );
  });

  it("treats an empty 409 as a failure", () => {
    const outcome = classifyWorkflowStopError(new Error("409: "));
    expect(outcome).toEqual({ kind: "failed", message: "HTTP 409" });
    expect(isNeutralStopOutcome(outcome)).toBe(false);
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
  it("treats 405 (route exists, POST-only) as supported", async () => {
    const fetchMock = vi
      .fn<(url: string, init?: RequestInit) => Promise<{ status: number }>>()
      .mockResolvedValue({ status: 405 });
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.probeAgentTeamWorkflowStop()).resolves.toBe("supported");
    // The probe must stay a GET on the stop route: a POST would stop a
    // workflow instead of asking whether the route exists.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/team/workflow/stop");
    expect(init?.method).toBeUndefined();
    vi.unstubAllGlobals();
  });

  it("treats 200 as supported", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status: 200 }));
    await expect(api.probeAgentTeamWorkflowStop()).resolves.toBe("supported");
    vi.unstubAllGlobals();
  });

  it("treats 404 (older runtime) as unsupported", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status: 404 }));
    await expect(api.probeAgentTeamWorkflowStop()).resolves.toBe("unsupported");
    vi.unstubAllGlobals();
  });

  it.each([502, 503, 500, 401, 403])(
    "leaves %i unknown instead of claiming an old runtime",
    async (status) => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status }));
      await expect(api.probeAgentTeamWorkflowStop()).resolves.toBe("unknown");
      vi.unstubAllGlobals();
    }
  );

  it("leaves a network failure unknown", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch"))
    );
    await expect(api.probeAgentTeamWorkflowStop()).resolves.toBe("unknown");
    vi.unstubAllGlobals();
  });

  it("recovers on a manual re-probe after a transient failure", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({ status: 405 });
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.probeAgentTeamWorkflowStop()).resolves.toBe("unknown");
    await expect(api.probeAgentTeamWorkflowStop()).resolves.toBe("supported");
    vi.unstubAllGlobals();
  });
});

describe("stop control rendering", () => {
  it("still offers Stop and a re-probe when the probe is unknown", () => {
    const control = workflowStopControl("unknown");
    expect(control.canStop).toBe(true);
    expect(control.canRetryProbe).toBe(true);
    expect(control.hint).toContain("重新检测");
  });

  it("keeps Stop enabled when supported, without a retry", () => {
    const control = workflowStopControl("supported");
    expect(control.canStop).toBe(true);
    expect(control.canRetryProbe).toBe(false);
    expect(control.hint).toContain("终止受控工作流");
  });

  it("disables Stop only for a proven older runtime", () => {
    const control = workflowStopControl("unsupported");
    expect(control.canStop).toBe(false);
    expect(control.canRetryProbe).toBe(false);
    expect(control.hint).toContain("不支持停止工作流");
  });

  it("stays usable before the first probe answers", () => {
    const control = workflowStopControl(null);
    expect(control.canStop).toBe(true);
    expect(control.canRetryProbe).toBe(false);
  });
});
