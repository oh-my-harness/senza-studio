import type { AgentTeamStartupRecovery, AgentTeamProject } from "../../types";
import type { ConversationItem } from "../../hooks/useAgentTeamWorkspace";

const RECOVERY_REASONS: Record<string, string> = {
  invalid_spec: "配置无效",
  workspace_unauthorized: "工作区未授权",
  workspace_check: "工作区检查失败",
  team_create: "团队创建失败",
};

function agentStatusDotClass(status: string) {
  if (status === "busy") return "bg-amber-400";
  if (status === "error" || status === "failed") return "bg-red-500";
  if (status === "idle" || status === "ready") return "bg-emerald-400";
  return "bg-gray-300";
}

function avatarColor(seed: string) {
  const palette = [
    "bg-blue-500",
    "bg-emerald-500",
    "bg-violet-500",
    "bg-orange-500",
    "bg-pink-500",
    "bg-cyan-600",
    "bg-indigo-500",
  ];
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) >>> 0;
  }
  return palette[hash % palette.length];
}

export default function AgentTeamSidebar({
  teams,
  selectedTeamId,
  selectedTeam,
  activeConversation,
  conversationList,
  recovery,
  members,
  selectTeam,
  selectConversation,
  loadPulse,
  onOpenNewTeam,
  onOpenSettings,
  onOpenMembers,
}: {
  teams: AgentTeamProject[];
  selectedTeamId: string | null;
  selectedTeam: AgentTeamProject | null;
  activeConversation: string;
  conversationList: ConversationItem[];
  recovery: AgentTeamStartupRecovery | null;
  members: number;
  selectTeam: (teamId: string) => void;
  selectConversation: (conversationId: string) => void;
  loadPulse: (teamId: string) => Promise<void> | void;
  onOpenNewTeam: () => void;
  onOpenSettings: () => void;
  onOpenMembers: () => void;
}) {
  return (
    <aside className="flex w-72 min-w-0 flex-col border-r border-gray-200 bg-[#F7F7F7]">
      <div className="flex items-center gap-2 border-b border-gray-200 px-3 py-2">
        <select
          value={selectedTeamId ?? ""}
          onChange={(event) => selectTeam(event.target.value)}
          aria-label="选择团队"
          className="min-w-0 flex-1 rounded-lg border border-gray-300 bg-white px-2 py-1.5 text-sm"
        >
          <option value="" disabled>
            选择团队
          </option>
          {teams.map((team) => (
            <option key={team.id} value={team.id}>
              {team.id}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={onOpenNewTeam}
          title="新建团队"
          aria-label="新建团队"
          className="rounded-lg bg-emerald-500 px-2.5 py-1.5 text-sm font-medium text-white hover:bg-emerald-600"
        >
          ＋
        </button>
        <button
          type="button"
          onClick={onOpenSettings}
          title="Runtime 设置"
          aria-label="打开 Runtime 设置"
          className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-200 hover:text-gray-700"
        >
          ⚙
        </button>
      </div>

      {selectedTeam && (
        <div className="min-h-0 flex-1 overflow-y-auto border-t border-gray-200">
          {conversationList.map((conversation) => (
            <button
              key={conversation.id}
              type="button"
              onClick={() => selectConversation(conversation.id)}
              className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-left ${
                activeConversation === conversation.id
                  ? "bg-emerald-100"
                  : "hover:bg-gray-100"
              }`}
            >
              <div
                className={`relative flex h-10 w-10 flex-none items-center justify-center rounded-lg text-sm font-semibold text-white ${
                  conversation.id === "team"
                    ? "bg-emerald-500"
                    : avatarColor(conversation.id)
                }`}
              >
                {conversation.id === "team"
                  ? "群"
                  : conversation.id.slice(0, 1).toUpperCase()}
                {conversation.status && (
                  <>
                    {conversation.status === "busy" && (
                      <span
                        aria-label="Agent 工作中"
                        title="Agent 工作中"
                        className="absolute -bottom-0.5 -right-0.5 h-3 w-3 animate-spin rounded-full border-2 border-blue-500 border-t-transparent"
                      />
                    )}
                    <span
                      className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-white ${agentStatusDotClass(conversation.status)}`}
                    />
                  </>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-gray-800">
                  {conversation.name}
                </p>
                <p className="truncate text-xs text-gray-400">
                  {conversation.preview || conversation.persona}
                </p>
              </div>
            </button>
          ))}
        </div>
      )}

      {recovery?.status === "degraded" && (
        <div className="border-t border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <strong>启动降级：</strong>
          已恢复 {recovery.restored_teams}/{recovery.persisted_teams} 个团队。
          {recovery.failed_teams.length > 0 && (
            <ul className="mt-1 list-disc pl-4">
              {recovery.failed_teams.map((failure) => (
                <li key={`${failure.team_id}:${failure.reason}`}>
                  {failure.team_id}: {RECOVERY_REASONS[failure.reason] ?? failure.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {selectedTeam && (
        <div className="border-t border-gray-200 px-3 py-2">
          <button
            type="button"
            onClick={() => {
              void loadPulse(selectedTeam.id);
              onOpenMembers();
            }}
            className="w-full rounded-lg border border-emerald-500 px-3 py-1.5 text-xs font-medium text-emerald-600 hover:bg-emerald-50"
          >
            成员管理（{members}）
          </button>
        </div>
      )}
    </aside>
  );
}
