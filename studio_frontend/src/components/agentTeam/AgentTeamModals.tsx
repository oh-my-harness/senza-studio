import type {
  AgentTeamMember,
  AgentTeamSettings,
  AgentTeamTemplate,
  AgentTeamProject,
  AgentTeamPulse,
} from "../../types";
import type { AgentTeamMemberDraft } from "../../hooks/useAgentTeamWorkspace";

const MEMBER_MODEL_OPTIONS = ["strong", "main", "cheap"];

function Modal({
  open,
  title,
  onClose,
  children,
  wide,
  error,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
  error?: string | null;
}) {
  return (
    <div
      style={{ display: open ? "flex" : "none" }}
      className="fixed inset-0 z-40 items-center justify-center bg-black/40 p-4"
    >
      <div
        className={`flex max-h-[85vh] w-full ${wide ? "max-w-2xl" : "max-w-md"} flex-col overflow-hidden rounded-2xl bg-white shadow-xl`}
      >
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-3">
          <h2 className="text-base font-semibold text-gray-800">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭弹窗"
            className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          >
            ✕
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {error && (
            <div
              className="mb-3 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
              role="alert"
            >
              {error}
            </div>
          )}
          {children}
        </div>
      </div>
    </div>
  );
}

function agentStatusClass(status: string) {
  if (status === "busy") return "bg-amber-100 text-amber-800";
  if (status === "error" || status === "failed") return "bg-red-100 text-red-700";
  if (status === "idle" || status === "ready") return "bg-emerald-100 text-emerald-800";
  return "bg-gray-100 text-gray-700";
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

export function AgentTeamNewTeamModal({
  open,
  error,
  newTeamId,
  setNewTeamId,
  newTeamName,
  setNewTeamName,
  newTeamTemplate,
  setNewTeamTemplate,
  newTeamRepo,
  setNewTeamRepo,
  templates,
  busyAction,
  onCreateTeam,
  onClose,
}: {
  open: boolean;
  error: string | null;
  newTeamId: string;
  setNewTeamId: (value: string) => void;
  newTeamName: string;
  setNewTeamName: (value: string) => void;
  newTeamTemplate: string;
  setNewTeamTemplate: (value: string) => void;
  newTeamRepo: string;
  setNewTeamRepo: (value: string) => void;
  templates: AgentTeamTemplate[];
  busyAction: string | null;
  onCreateTeam: () => void;
  onClose: () => void;
}) {
  return (
    <Modal open={open} error={error} title="新建团队" onClose={onClose}>
      <div className="space-y-2">
        <input
          value={newTeamId}
          onChange={(event) => setNewTeamId(event.target.value)}
          placeholder="团队 ID"
          aria-label="团队 ID"
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <input
          value={newTeamName}
          onChange={(event) => setNewTeamName(event.target.value)}
          placeholder="显示名称（可选）"
          aria-label="团队显示名称"
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <select
          value={newTeamTemplate}
          onChange={(event) => setNewTeamTemplate(event.target.value)}
          aria-label="团队模板"
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        >
          <option value="">空白团队</option>
          {templates.map((template) => (
            <option key={`${template.id}:${template.version}`} value={template.id}>
              {template.name}（{template.id}）
            </option>
          ))}
        </select>
        <input
          value={newTeamRepo}
          onChange={(event) => setNewTeamRepo(event.target.value)}
          placeholder="已授权工作区路径（可选）"
          aria-label="团队工作区路径"
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <button
          type="button"
          onClick={onCreateTeam}
          disabled={busyAction === "create"}
          className="w-full rounded-lg bg-emerald-500 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
        >
          创建团队
        </button>
      </div>
    </Modal>
  );
}

export function AgentTeamSettingsModal({
  open,
  error,
  settings,
  settingsReady,
  busyAction,
  settingsStrongModel,
  setSettingsStrongModel,
  settingsMainModel,
  setSettingsMainModel,
  settingsCheapModel,
  setSettingsCheapModel,
  settingsBaseUrl,
  setSettingsBaseUrl,
  settingsScoutInterval,
  setSettingsScoutInterval,
  settingsApiKey,
  setSettingsApiKey,
  onSaveSettings,
  onClose,
}: {
  open: boolean;
  error: string | null;
  settings: AgentTeamSettings | null;
  settingsReady: boolean;
  busyAction: string | null;
  settingsStrongModel: string;
  setSettingsStrongModel: (value: string) => void;
  settingsMainModel: string;
  setSettingsMainModel: (value: string) => void;
  settingsCheapModel: string;
  setSettingsCheapModel: (value: string) => void;
  settingsBaseUrl: string;
  setSettingsBaseUrl: (value: string) => void;
  settingsScoutInterval: string;
  setSettingsScoutInterval: (value: string) => void;
  settingsApiKey: string;
  setSettingsApiKey: (value: string) => void;
  onSaveSettings: () => void;
  onClose: () => void;
}) {
  return (
    <Modal open={open} error={error} title="Runtime 设置" onClose={onClose}>
      <section
        className="space-y-2"
        data-testid="agent-team-runtime-settings"
        data-ready={settingsReady ? "true" : "false"}
      >
        <input
          value={settingsStrongModel}
          onChange={(event) => setSettingsStrongModel(event.target.value)}
          placeholder="strong 模型"
          aria-label="AgentTeam strong 模型"
          disabled={!settingsReady || busyAction === "settings"}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <input
          value={settingsMainModel}
          onChange={(event) => setSettingsMainModel(event.target.value)}
          placeholder="main 模型"
          aria-label="AgentTeam main 模型"
          disabled={!settingsReady || busyAction === "settings"}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <input
          value={settingsCheapModel}
          onChange={(event) => setSettingsCheapModel(event.target.value)}
          placeholder="cheap 模型（可选）"
          aria-label="AgentTeam cheap 模型"
          disabled={!settingsReady || busyAction === "settings"}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <input
          value={settingsBaseUrl}
          onChange={(event) => setSettingsBaseUrl(event.target.value)}
          placeholder="API base URL（可选）"
          aria-label="AgentTeam API base URL"
          disabled={!settingsReady || busyAction === "settings"}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <input
          value={settingsScoutInterval}
          onChange={(event) => setSettingsScoutInterval(event.target.value)}
          placeholder="Scout 间隔秒数"
          aria-label="AgentTeam scout 间隔秒数"
          disabled={!settingsReady || busyAction === "settings"}
          inputMode="numeric"
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <input
          value={settingsApiKey}
          onChange={(event) => setSettingsApiKey(event.target.value)}
          type="password"
          placeholder={settings?.api_key_set ? "已设置（输入替换）" : "API key"}
          aria-label="AgentTeam API key"
          disabled={!settingsReady || busyAction === "settings"}
          autoComplete="new-password"
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <button
          type="button"
          onClick={onSaveSettings}
          disabled={!settingsReady || busyAction === "settings"}
          className="w-full rounded-lg bg-emerald-500 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
        >
          保存 Runtime 设置
        </button>
      </section>
    </Modal>
  );
}

export function AgentTeamMembersModal({
  open,
  error,
  selectedTeam,
  members,
  pulseByAgentId,
  memberDraft,
  setMemberDraft,
  newMember,
  setNewMember,
  busyAction,
  onSaveMember,
  onAddMember,
  onDeleteMember,
  onClose,
}: {
  open: boolean;
  error: string | null;
  selectedTeam: AgentTeamProject | null;
  members: AgentTeamMember[];
  pulseByAgentId: Map<string, AgentTeamPulse["agents"][number]>;
  memberDraft: AgentTeamMemberDraft | null;
  setMemberDraft: React.Dispatch<React.SetStateAction<AgentTeamMemberDraft | null>>;
  newMember: { id: string; persona: string; role_label: string; model: string; toolkits: string };
  setNewMember: React.Dispatch<React.SetStateAction<{ id: string; persona: string; role_label: string; model: string; toolkits: string }>>;
  busyAction: string | null;
  onSaveMember: () => void;
  onAddMember: () => void;
  onDeleteMember: (memberId: string) => void;
  onClose: () => void;
}) {
  return (
    <Modal
      open={open}
      error={error}
      title={`成员管理 · ${selectedTeam?.id ?? ""}`}
      onClose={onClose}
      wide
    >
      {memberDraft && (
        <form className="mb-5 space-y-2" data-testid="agent-team-edit-member">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            编辑 {memberDraft.id}
          </h3>
          <input
            value={memberDraft.id}
            readOnly
            aria-label="成员 ID"
            className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-500"
          />
          <textarea
            value={memberDraft.persona}
            onChange={(event) =>
              setMemberDraft((current) =>
                current ? { ...current, persona: event.target.value } : current
              )
            }
            placeholder="性格 / persona"
            aria-label="成员 persona"
            rows={3}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
          />
          <input
            value={memberDraft.role_label}
            onChange={(event) =>
              setMemberDraft((current) =>
                current ? { ...current, role_label: event.target.value } : current
              )
            }
            placeholder="角色标签"
            aria-label="成员角色标签"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
          />
          <select
            value={memberDraft.model}
            onChange={(event) =>
              setMemberDraft((current) =>
                current ? { ...current, model: event.target.value } : current
              )
            }
            aria-label="成员模型"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
          >
            {MEMBER_MODEL_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
          <input
            value={memberDraft.toolkits}
            onChange={(event) =>
              setMemberDraft((current) =>
                current ? { ...current, toolkits: event.target.value } : current
              )
            }
            placeholder="工具包，逗号分隔"
            aria-label="成员工具包"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
          />
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onSaveMember}
              disabled={busyAction === `save-member:${memberDraft.id}`}
              className="flex-1 rounded-lg bg-emerald-500 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
            >
              保存成员
            </button>
            <button
              type="button"
              onClick={() => setMemberDraft(null)}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-600 hover:bg-gray-100"
            >
              取消
            </button>
          </div>
        </form>
      )}

      <form className="mb-5 space-y-2" data-testid="agent-team-add-member">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          添加成员
        </h3>
        <input
          value={newMember.id}
          onChange={(event) =>
            setNewMember((current) => ({ ...current, id: event.target.value }))
          }
          placeholder="成员 ID"
          aria-label="新成员 ID"
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <textarea
          value={newMember.persona}
          onChange={(event) =>
            setNewMember((current) => ({ ...current, persona: event.target.value }))
          }
          placeholder="性格 / persona"
          aria-label="新成员 persona"
          rows={2}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <input
          value={newMember.role_label}
          onChange={(event) =>
            setNewMember((current) => ({
              ...current,
              role_label: event.target.value,
            }))
          }
          placeholder="角色标签（默认使用 ID）"
          aria-label="新成员角色标签"
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <select
          value={newMember.model}
          onChange={(event) =>
            setNewMember((current) => ({ ...current, model: event.target.value }))
          }
          aria-label="新成员模型"
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        >
          {MEMBER_MODEL_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
        <input
          value={newMember.toolkits}
          onChange={(event) =>
            setNewMember((current) => ({
              ...current,
              toolkits: event.target.value,
            }))
          }
          placeholder="工具包，逗号分隔"
          aria-label="新成员工具包"
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <button
          type="button"
          onClick={onAddMember}
          disabled={busyAction === "add-member"}
          className="w-full rounded-lg bg-emerald-500 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
        >
          添加成员
        </button>
      </form>

      <div className="space-y-2" data-testid="agent-team-members">
        {members.map((member) => {
          const agent = pulseByAgentId.get(member.id);
          return (
            <div
              key={member.id}
              className="flex items-center gap-3 rounded-lg border border-gray-200 px-3 py-2"
            >
              <div
                className={`flex h-9 w-9 flex-none items-center justify-center rounded-lg text-sm font-semibold text-white ${avatarColor(member.id)}`}
              >
                {member.id.slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-800">
                    {member.role_label || member.id}
                  </span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs ${agentStatusClass(agent?.status ?? "unknown")}`}
                  >
                    {agent?.status ?? "unknown"}
                  </span>
                </div>
                <p className="truncate text-xs text-gray-500" title={member.persona}>
                  {member.persona || "未设置 persona"}
                </p>
                <p className="text-xs text-gray-400">
                  {[member.model, member.toolkits.join(", ")].filter(Boolean).join(" · ")}
                </p>
              </div>
              <button
                type="button"
                onClick={() =>
                  setMemberDraft({ ...member, toolkits: member.toolkits.join(", ") })
                }
                className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-100"
              >
                编辑
              </button>
              <button
                type="button"
                onClick={() => onDeleteMember(member.id)}
                disabled={busyAction === `delete-member:${member.id}`}
                className="rounded border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                删除成员
              </button>
            </div>
          );
        })}
        {members.length === 0 && (
          <p className="rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-500">
            团队没有成员
          </p>
        )}
      </div>
    </Modal>
  );
}
