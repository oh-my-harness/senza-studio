// studio_frontend/src/agentTeamWorkspaceGrant.ts
// Create Team 工作区授权流:runtime 对未授权 repo_path 返回 403
// "workspace is not authorized; grant it before registering"。前端识别这个
// 具体错误,经用户显式确认后调用已有的 POST /api/team/fs/grants(只授予用户
// 输入的确切路径),然后原样重试一次 Create Team。不预授权、不授予父目录。

/** Runtime 对未授权工作区的权威 403 错误文案。 */
export const WORKSPACE_UNAUTHORIZED_ERROR = "workspace is not authorized; grant it before registering";

/** Create Team 请求的输入(retry 需要原样重放)。 */
export interface CreateTeamInput {
  id: string;
  name?: string;
  template_id?: string;
  repo_path?: string;
}

/**
 * 判断一个错误是否是 runtime 的"工作区未授权"403。
 * fetchJson 抛出的错误形如 `${status}: ${body}`,例如
 * `403: {"error":"workspace is not authorized; grant it before registering","ok":false}`。
 */
export function isWorkspaceUnauthorizedError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  if (!error.message.startsWith("403")) return false;
  return error.message.includes(WORKSPACE_UNAUTHORIZED_ERROR);
}

/** 从 Create Team 输入中取出待授权的确切工作区路径;没有则返回 null。 */
export function workspacePathForCreate(input: CreateTeamInput): string | null {
  const path = input.repo_path?.trim();
  return path ? path : null;
}

/** 授权确认弹窗文案(精确到路径,让用户知道自己授的是什么权)。 */
export function workspaceGrantConfirmMessage(path: string): string {
  return `工作区尚未授权。允许运行时访问 ${path} 并创建团队吗?`;
}
