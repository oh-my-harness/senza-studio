import type { AgentTeamPulse, AgentTeamProject, AgentTeamMember } from "../../types";
import type { ChatItem } from "../../hooks/useAgentTeamWorkspace";
import type { AgentTeamEventConnectionState } from "../../agentTeamEvents";

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

export default function AgentTeamChatPanel({
  selectedTeam,
  activeConversation,
  activeMember,
  members,
  pulse,
  pulseByAgentId,
  memberById,
  connectionState,
  loadError,
  actionError,
  actionNotice,
  busyAction,
  chatFilter,
  setChatFilter,
  showMentionMenu,
  setShowMentionMenu,
  messageText,
  setMessageText,
  chatEndRef,
  chatItems,
  onRestartTeam,
  onDeleteTeam,
  onAbort,
  onSendMessage,
}: {
  selectedTeam: { id: string };
  activeConversation: string;
  activeMember: AgentTeamMember | null;
  members: AgentTeamMember[];
  pulse: AgentTeamPulse | null;
  pulseByAgentId: Map<string, AgentTeamPulse["agents"][number]>;
  memberById: Map<string, AgentTeamMember>;
  connectionState: AgentTeamEventConnectionState;
  loadError: string | null;
  actionError: string | null;
  actionNotice: string | null;
  busyAction: string | null;
  chatEndRef: React.RefObject<HTMLDivElement>;
  chatItems: {
    key: string;
    kind: "message" | "thought" | "system";
    from: string;
    text: string;
    mine: boolean;
    time?: string;
    count?: number;
  }[];
  chatFilter: string;
  setChatFilter: (value: string) => void;
  messageText: string;
  setMessageText: React.Dispatch<React.SetStateAction<string>>;
  showMentionMenu: boolean;
  setShowMentionMenu: React.Dispatch<React.SetStateAction<boolean>>;
  onRestartTeam: (teamId: string) => void;
  onDeleteTeam: (teamId: string) => void;
  onAbort: () => void;
  onSendMessage: () => void;
}) {
  return (
    <main className="flex min-w-0 flex-1 flex-col bg-[#EDEDED]">
      <header className="flex items-center gap-2 border-b border-gray-200 bg-white px-3 py-2">
        <div
          className={`flex h-9 w-9 flex-none items-center justify-center rounded-lg text-sm font-semibold text-white ${
            activeConversation === "team"
              ? "bg-emerald-500"
              : avatarColor(activeConversation)
          }`}
        >
          {activeConversation === "team"
            ? "群"
            : activeConversation.slice(0, 1).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-gray-800">
            {activeConversation === "team"
              ? `群聊 · ${selectedTeam.id}`
              : activeMember?.role_label || activeConversation}
            {((activeConversation === "team" &&
              [...pulseByAgentId.values()].some(
                (agent) => agent.status === "busy"
              )) ||
              (activeConversation !== "team" &&
                pulseByAgentId.get(activeConversation)?.status === "busy")) && (
              <span
                aria-label="Agent 工作中"
                title="Agent 工作中"
                className="ml-2 inline-block h-3 w-3 animate-spin rounded-full border-2 border-blue-500 border-t-transparent align-[-1px]"
              />
            )}
          </p>
          <p className="truncate text-xs text-gray-400">
            {activeConversation === "team"
              ? `所有成员可见 · 待处理 ${pulse?.pending.length ?? 0} · issue ${pulse?.issues.pending ?? 0} · 定时器 ${pulse?.timers.pending ?? 0}`
              : activeMember?.persona || "私聊"}
          </p>
        </div>
        <select
          id="agent-team-chat-filter"
          value={chatFilter}
          onChange={(event) => setChatFilter(event.target.value)}
          aria-label="筛选聊天记录"
          className="h-8 w-28 rounded-lg border border-gray-200 bg-white px-2 text-xs text-gray-600"
        >
          <option value="all">全部</option>
          <option value="operator">我</option>
          {members.map((member) => (
            <option key={member.id} value={member.id}>
              {member.role_label || member.id}
            </option>
          ))}
        </select>
        {activeConversation === "team" && members.length > 0 && (
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowMentionMenu((current) => !current)}
              aria-expanded={showMentionMenu}
              className="h-8 rounded-lg border border-gray-200 px-2 text-xs text-gray-600 hover:border-emerald-300 hover:text-emerald-600"
            >
              @
            </button>
            {showMentionMenu && (
              <>
                <button
                  type="button"
                  aria-label="关闭成员列表"
                  onClick={() => setShowMentionMenu(false)}
                  className="fixed inset-0 z-10 cursor-default"
                />
                <div className="absolute right-0 top-full z-20 mt-1 max-h-48 w-48 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg">
                  {members.map((member) => (
                    <button
                      key={member.id}
                      type="button"
                      onClick={() => {
                        setMessageText((current) => `${current ? `${current} ` : ""}@${member.id} `);
                        setShowMentionMenu(false);
                      }}
                      className="block w-full truncate px-3 py-2 text-left text-xs text-gray-700 hover:bg-emerald-50 hover:text-emerald-700"
                    >
                      @{member.id}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
        <button
          type="button"
          data-testid="agent-team-restart"
          onClick={() => onRestartTeam(selectedTeam.id)}
          disabled={busyAction === `restart:${selectedTeam.id}`}
          title={busyAction === `restart:${selectedTeam.id}` ? "重启中" : "重启团队"}
          aria-label="重启团队"
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-emerald-200 text-sm text-emerald-600 hover:bg-emerald-50 disabled:opacity-40"
        >
          {busyAction === `restart:${selectedTeam.id}` ? "…" : "↻"}
        </button>
        <button
          type="button"
          onClick={() => onDeleteTeam(selectedTeam.id)}
          disabled={busyAction === `delete:${selectedTeam.id}`}
          title={busyAction === `delete:${selectedTeam.id}` ? "删除中" : "删除团队"}
          aria-label="删除团队"
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-red-200 text-sm text-red-600 hover:bg-red-50 disabled:opacity-40"
        >
          {busyAction === `delete:${selectedTeam.id}` ? "…" : "🗑"}
        </button>
        <button
          type="button"
          onClick={onAbort}
          disabled={busyAction === "abort"}
          aria-label="打断 Agent"
          title={activeConversation === "team" ? "打断所有成员" : "打断当前 Agent"}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-red-200 text-sm text-red-600 hover:bg-red-50 disabled:opacity-40"
        >
          {busyAction === "abort" ? "…" : "■"}
        </button>
        <span
          className="flex h-8 items-center text-xs text-gray-500"
          data-testid="agent-team-connection"
          title={connectionState === "open" ? "已连接" : connectionState}
        >
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              connectionState === "open"
                ? "bg-emerald-500"
                : connectionState === "connecting"
                  ? "bg-amber-500"
                  : "bg-red-500"
            }`}
          />
          {connectionState !== "open" && <span className="ml-1">{connectionState}</span>}
        </span>
      </header>

      {(loadError || actionError || actionNotice) && (
        <div
          className={`mx-3 mt-2 rounded-lg border px-3 py-2 text-xs ${
            actionError || loadError
              ? "border-red-300 bg-red-50 text-red-700"
              : "border-emerald-200 bg-emerald-50 text-emerald-700"
          }`}
          data-testid="agent-team-action-error"
          role="alert"
        >
          {loadError ?? actionError ?? actionNotice}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <div className="space-y-3" data-testid="agent-team-conversation">
          {chatItems.length === 0 && (
            <p className="py-8 text-center text-sm text-gray-400">
              {activeConversation === "team"
                ? "暂无聊天记录；在下方输入消息开始群聊"
                : "暂无与该成员的对话；在下方输入消息开始私聊"}
            </p>
          )}
          {chatItems.map((item) =>
            item.kind === "system" ? (
              <p key={item.key} className="text-center text-xs text-red-500">
                ⚠ {item.from}: {item.text}
                {item.count && item.count > 1 ? ` ×${item.count}` : ""}
              </p>
            ) : (
              <div key={item.key} className={`flex gap-2 ${item.mine ? "flex-row-reverse" : ""}`}>
                <div
                  className={`flex h-9 w-9 flex-none items-center justify-center rounded-lg text-sm font-semibold text-white ${
                    item.mine ? "bg-emerald-600" : avatarColor(item.from)
                  }`}
                >
                  {item.mine ? "我" : item.from.slice(0, 1).toUpperCase()}
                </div>
                <div className="max-w-[70%]">
                  <p className={`text-xs text-gray-400 ${item.mine ? "text-right" : ""}`}>
                    {item.mine
                      ? "我"
                      : memberById.get(item.from)?.role_label || item.from}{" "}
                    {item.time}
                  </p>
                  <div
                    className={`mt-1 inline-block whitespace-pre-wrap rounded-xl px-3 py-2 text-sm ${
                      item.kind === "thought"
                        ? "border border-violet-100 bg-violet-50 text-xs italic text-violet-700"
                        : item.mine
                          ? "bg-[#95EC69] text-gray-900"
                          : "bg-white text-gray-800"
                    }`}
                  >
                    {item.kind === "thought" && "💭 "}
                    {item.text}
                  </div>
                </div>
              </div>
            )
          )}
          <div ref={chatEndRef} />
        </div>
      </div>

      <div className="border-t border-gray-200 bg-white px-4 py-3">
        <div className="flex items-end gap-2">
          <textarea
            value={messageText}
            onChange={(event) => setMessageText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                onSendMessage();
              }
            }}
            placeholder={
              activeConversation === "team"
                ? "发送到团队群聊；Enter 发送，Shift+Enter 换行"
                : `私聊 ${activeMember?.role_label || activeConversation}；Enter 发送，Shift+Enter 换行`
            }
            aria-label="团队消息"
            rows={2}
            className="min-h-0 flex-1 resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-emerald-400 focus:outline-none"
          />
          <button
            type="button"
            onClick={onSendMessage}
            disabled={busyAction === "send" || !messageText.trim()}
            className="rounded-lg bg-emerald-500 px-5 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
          >
            发送
          </button>
        </div>
      </div>
    </main>
  );
}
