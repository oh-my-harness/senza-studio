import { describe, expect, it, vi } from "vitest";

import {
  createTeamWithWorkspaceConsent,
  isWorkspaceUnauthorizedError,
  workspaceGrantConfirmMessage,
  workspacePathForCreate,
} from "./agentTeamWorkspaceGrant";

const UNAUTHORIZED = new Error(
  '403: {"ok":false,"error":"workspace is not authorized; grant it before registering"}'
);
const INPUT = { id: "team-1", repo_path: "  /work/repo  " };

function deps(overrides: Partial<Parameters<typeof createTeamWithWorkspaceConsent>[1]> = {}) {
  return {
    createTeam: vi.fn().mockResolvedValue({ ok: true }),
    addGrant: vi.fn().mockResolvedValue({ id: "grant-1" }),
    confirm: vi.fn().mockReturnValue(true),
    ...overrides,
  };
}

describe("workspace grant consent", () => {
  it("creates directly when the workspace is authorized", async () => {
    const d = deps();
    const outcome = await createTeamWithWorkspaceConsent(INPUT, d);
    expect(outcome).toBe("created");
    expect(d.createTeam).toHaveBeenCalledTimes(1);
    expect(d.confirm).not.toHaveBeenCalled();
    expect(d.addGrant).not.toHaveBeenCalled();
  });

  it("recognizes only the runtime's exact 403 message", () => {
    expect(isWorkspaceUnauthorizedError(UNAUTHORIZED)).toBe(true);
    expect(
      isWorkspaceUnauthorizedError(new Error("403: forbidden workspace"))
    ).toBe(false);
    expect(
      isWorkspaceUnauthorizedError(
        new Error('409: {"error":"workspace is not authorized; grant it before registering"}')
      )
    ).toBe(false);
  });

  it("grants the exact trimmed path after confirmation, then retries once", async () => {
    const createTeam = vi
      .fn()
      .mockRejectedValueOnce(UNAUTHORIZED)
      .mockResolvedValueOnce({ ok: true });
    const d = deps({ createTeam });
    const outcome = await createTeamWithWorkspaceConsent(INPUT, d);
    expect(outcome).toBe("created");
    expect(d.confirm).toHaveBeenCalledWith(
      workspaceGrantConfirmMessage("/work/repo")
    );
    expect(d.addGrant).toHaveBeenCalledTimes(1);
    expect(d.addGrant).toHaveBeenCalledWith("/work/repo");
    expect(createTeam).toHaveBeenCalledTimes(2);
    expect(createTeam.mock.calls[1][0]).toBe(INPUT);
  });

  it("returns cancelled without granting or retrying", async () => {
    const d = deps({
      createTeam: vi.fn().mockRejectedValueOnce(UNAUTHORIZED),
      confirm: vi.fn().mockReturnValue(false),
    });
    const outcome = await createTeamWithWorkspaceConsent(INPUT, d);
    expect(outcome).toBe("cancelled");
    expect(d.addGrant).not.toHaveBeenCalled();
    expect(d.createTeam).toHaveBeenCalledTimes(1);
  });

  it("does not prompt when the request carries no repo path", async () => {
    const d = deps({
      createTeam: vi.fn().mockRejectedValueOnce(UNAUTHORIZED),
    });
    await expect(
      createTeamWithWorkspaceConsent({ id: "team-1" }, d)
    ).rejects.toBe(UNAUTHORIZED);
    expect(d.confirm).not.toHaveBeenCalled();
  });

  it("surfaces a grant failure without retrying create", async () => {
    const grantError = new Error(
      '400: {"ok":false,"error":"invalid workspace grant: /work/repo"}'
    );
    const d = deps({
      createTeam: vi.fn().mockRejectedValueOnce(UNAUTHORIZED),
      addGrant: vi.fn().mockRejectedValueOnce(grantError),
    });
    await expect(createTeamWithWorkspaceConsent(INPUT, d)).rejects.toBe(
      grantError
    );
    expect(d.createTeam).toHaveBeenCalledTimes(1);
    expect(d.addGrant).toHaveBeenCalledTimes(1);
  });

  it("does not loop when the retry also fails", async () => {
    const retryError = new Error(
      '400: {"ok":false,"error":"not a git repo: /work/repo"}'
    );
    const d = deps({
      createTeam: vi
        .fn()
        .mockRejectedValueOnce(UNAUTHORIZED)
        .mockRejectedValueOnce(retryError),
    });
    await expect(createTeamWithWorkspaceConsent(INPUT, d)).rejects.toBe(
      retryError
    );
    expect(d.createTeam).toHaveBeenCalledTimes(2);
    expect(d.addGrant).toHaveBeenCalledTimes(1);
    expect(d.confirm).toHaveBeenCalledTimes(1);
  });

  it("keeps a blank repo path out of the prompt", () => {
    expect(workspacePathForCreate({ id: "x", repo_path: "   " })).toBeNull();
  });
});
