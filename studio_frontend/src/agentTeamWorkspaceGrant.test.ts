// studio_frontend/src/agentTeamWorkspaceGrant.test.ts
// Create Team 工作区授权流回归测试:已授权不弹授权、取消不授权、确认后
// 授权确切路径并恰好重试一次、授权/重试失败时错误保留且无循环。
//
// 仓库没有 jsdom/@testing-library(见 BottomPanel.activity.test.tsx 的说明),
// 所以用 vitest 的模块 mock 模拟 ../api 与 window.confirm,直接对
// createAgentTeamWithWorkspaceConsent 做行为断言。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const createAgentTeam = vi.fn();
const addAgentTeamWorkspaceGrant = vi.fn();

vi.mock("./api", () => ({
  api: {
    createAgentTeam: (...args: unknown[]) => createAgentTeam(...args),
    addAgentTeamWorkspaceGrant: (...args: unknown[]) =>
      addAgentTeamWorkspaceGrant(...args),
  },
}));

import { createAgentTeamWithWorkspaceConsent } from "./hooks/useAgentTeamWorkspace";

const WORKSPACE = "/workspace/test-project";
// Runtime add_workspace_grant 的权威错误文案(routes.rs 逐字匹配)。
const UNAUTHORIZED_403 = new Error(
  '403: {"error":"workspace is not authorized; grant it before registering","ok":false}'
);

function input(overrides: Record<string, unknown> = {}) {
  return { id: "demo", repo_path: WORKSPACE, ...overrides };
}

beforeEach(() => {
  createAgentTeam.mockReset();
  addAgentTeamWorkspaceGrant.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("create team workspace authorization flow", () => {
  it("already-authorized workspace: create succeeds and grant is not called", async () => {
    createAgentTeam.mockResolvedValueOnce({ ok: true });

    await createAgentTeamWithWorkspaceConsent(input(), () => {});

    expect(createAgentTeam).toHaveBeenCalledTimes(1);
    expect(addAgentTeamWorkspaceGrant).not.toHaveBeenCalled();
  });

  it("other 403s are not treated as authorization-required", async () => {
    createAgentTeam.mockRejectedValueOnce(
      new Error('403: {"error":"some other forbidden","ok":false}')
    );

    await expect(
      createAgentTeamWithWorkspaceConsent(input(), () => {})
    ).rejects.toThrow("some other forbidden");

    expect(addAgentTeamWorkspaceGrant).not.toHaveBeenCalled();
    expect(createAgentTeam).toHaveBeenCalledTimes(1);
  });

  it("unauthorized workspace: grant is not performed before user confirmation", async () => {
    createAgentTeam.mockRejectedValueOnce(UNAUTHORIZED_403);
    const confirm = vi.fn(() => false);
    vi.stubGlobal("window", { confirm });

    await createAgentTeamWithWorkspaceConsent(input(), () => {});

    expect(confirm).toHaveBeenCalledTimes(1);
    expect(addAgentTeamWorkspaceGrant).not.toHaveBeenCalled();
    expect(createAgentTeam).toHaveBeenCalledTimes(1);
  });

  it("user cancels: no grant and create is not retried", async () => {
    createAgentTeam.mockRejectedValueOnce(UNAUTHORIZED_403);
    vi.stubGlobal("window", { confirm: vi.fn(() => false) });

    await createAgentTeamWithWorkspaceConsent(input(), () => {});

    expect(createAgentTeam).toHaveBeenCalledTimes(1);
    expect(addAgentTeamWorkspaceGrant).not.toHaveBeenCalled();
  });

  it("user confirms: exact workspace is granted and create retried exactly once", async () => {
    createAgentTeam
      .mockRejectedValueOnce(UNAUTHORIZED_403)
      .mockResolvedValueOnce({ ok: true });
    addAgentTeamWorkspaceGrant.mockResolvedValueOnce({ id: "g1", path: WORKSPACE });
    const confirm = vi.fn(() => true);
    vi.stubGlobal("window", { confirm });
    const setError = vi.fn();

    await createAgentTeamWithWorkspaceConsent(input(), setError);

    expect(confirm).toHaveBeenCalledWith(
      expect.stringContaining(WORKSPACE)
    );
    expect(addAgentTeamWorkspaceGrant).toHaveBeenCalledTimes(1);
    expect(addAgentTeamWorkspaceGrant).toHaveBeenCalledWith(WORKSPACE);
    expect(createAgentTeam).toHaveBeenCalledTimes(2);
    expect(createAgentTeam).toHaveBeenNthCalledWith(2, input());
    expect(setError).toHaveBeenCalledWith(null);
  });

  it("grant is not granted for a parent directory", async () => {
    createAgentTeam.mockRejectedValueOnce(UNAUTHORIZED_403).mockResolvedValue({ ok: true });
    addAgentTeamWorkspaceGrant.mockResolvedValue({ id: "g1" });
    vi.stubGlobal("window", { confirm: vi.fn(() => true) });

    await createAgentTeamWithWorkspaceConsent(
      input({ repo_path: "/workspace/test-project" }),
      () => {}
    );

    expect(addAgentTeamWorkspaceGrant).toHaveBeenCalledWith(
      "/workspace/test-project"
    );
    expect(addAgentTeamWorkspaceGrant).not.toHaveBeenCalledWith(
      "/workspace"
    );
  });

  it("grant failure: create is not retried and the grant error surfaces", async () => {
    createAgentTeam.mockRejectedValueOnce(UNAUTHORIZED_403);
    addAgentTeamWorkspaceGrant.mockRejectedValueOnce(
      new Error('400: {"error":"invalid workspace grant: /no/such/dir"}')
    );
    vi.stubGlobal("window", { confirm: vi.fn(() => true) });

    await expect(
      createAgentTeamWithWorkspaceConsent(input(), () => {})
    ).rejects.toThrow("invalid workspace grant: /no/such/dir");

    expect(createAgentTeam).toHaveBeenCalledTimes(1);
  });

  it("create retry failure: failure surfaces and no repeated grant/create loop", async () => {
    createAgentTeam
      .mockRejectedValueOnce(UNAUTHORIZED_403)
      .mockRejectedValueOnce(new Error('409: {"error":"duplicate team id"}'));
    addAgentTeamWorkspaceGrant.mockResolvedValueOnce({ id: "g1" });
    vi.stubGlobal("window", { confirm: vi.fn(() => true) });

    await expect(
      createAgentTeamWithWorkspaceConsent(input(), () => {})
    ).rejects.toThrow("duplicate team id");

    expect(createAgentTeam).toHaveBeenCalledTimes(2);
    expect(addAgentTeamWorkspaceGrant).toHaveBeenCalledTimes(1);
  });

  it("unauthorized 403 without a repo path: surfaces the original error without prompting", async () => {
    createAgentTeam.mockRejectedValueOnce(UNAUTHORIZED_403);
    const confirm = vi.fn(() => true);
    vi.stubGlobal("window", { confirm });

    await expect(
      createAgentTeamWithWorkspaceConsent({ id: "demo" }, () => {})
    ).rejects.toThrow("workspace is not authorized");

    expect(confirm).not.toHaveBeenCalled();
    expect(addAgentTeamWorkspaceGrant).not.toHaveBeenCalled();
  });
});
