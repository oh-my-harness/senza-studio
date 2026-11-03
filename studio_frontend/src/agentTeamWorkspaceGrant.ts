// workspace grant consent flow for Create Team.
//
// The runtime is the authority: it rejects an unauthorized repo_path with
// 403 "workspace is not authorized; grant it before registering". Only that
// exact response triggers a confirmation. Nothing is granted before the user
// answers, and only the exact trimmed path from the form is granted.
import { apiErrorInfo, type CreateAgentTeamInput } from "./api";

export const WORKSPACE_UNAUTHORIZED_ERROR =
  "workspace is not authorized; grant it before registering";

export type CreateTeamOutcome = "created" | "cancelled";

export interface WorkspaceConsentDeps {
  createTeam: (input: CreateAgentTeamInput) => Promise<unknown>;
  addGrant: (path: string) => Promise<unknown>;
  confirm: (message: string) => boolean;
}

export function isWorkspaceUnauthorizedError(error: unknown): boolean {
  const { status, message } = apiErrorInfo(error);
  return status === 403 && message.includes(WORKSPACE_UNAUTHORIZED_ERROR);
}

/** Exact workspace path from the form; null when the form has no path. */
export function workspacePathForCreate(
  input: CreateAgentTeamInput
): string | null {
  const path = input.repo_path?.trim();
  return path ? path : null;
}

export function workspaceGrantConfirmMessage(path: string): string {
  return `工作区尚未授权。允许运行时访问 ${path} 并创建团队吗？`;
}

/**
 * Create a team, asking once for workspace authorization when the runtime
 * rejects the path.
 *
 * Returns "cancelled" when the user declines, so the caller keeps the form
 * intact instead of running its success path. Grant and retry failures throw:
 * create is attempted at most twice (original + one retry) and grant once.
 */
export async function createTeamWithWorkspaceConsent(
  input: CreateAgentTeamInput,
  deps: WorkspaceConsentDeps
): Promise<CreateTeamOutcome> {
  try {
    await deps.createTeam(input);
    return "created";
  } catch (error) {
    if (!isWorkspaceUnauthorizedError(error)) throw error;
    const path = workspacePathForCreate(input);
    if (!path) throw error;
    if (!deps.confirm(workspaceGrantConfirmMessage(path))) return "cancelled";
    await deps.addGrant(path);
    await deps.createTeam(input);
    return "created";
  }
}
