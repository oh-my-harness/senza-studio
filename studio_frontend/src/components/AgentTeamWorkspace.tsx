import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import {
  connectAgentTeamEvents,
  type AgentTeamEvent,
  type AgentTeamEventConnectionState,
} from "../agentTeamEvents";
import type {
  AgentTeamProject,
  AgentTeamPulse,
  AgentTeamMember,
  AgentTeamStartupRecovery,
  AgentTeamSettings,
  AgentTeamTemplate,
} from "../types";

const TEAM_ID_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;

type AgentTeamMemberDraft = Omit<AgentTeamMember, "toolkits"> & {
  toolkits: string;
};

const RECOVERY_REASONS: Record<string, string> = {
  invalid_spec: "配置无效",
  workspace_unauthorized: "工作区未授权",
  workspace_check: "工作区检查失败",
  team_create: "团队创建失败",
};

function agentStatusClass(status: string) {
  if (status === "busy") return "bg-amber-100 text-amber-800";
  if (status === "error" || status === "failed") return "bg-red-100 text-red-700";
  if (status === "idle" || status === "ready") return "bg-emerald-100 text-emerald-800";
  return "bg-gray-100 text-gray-700";
}

function eventSummary(event: AgentTeamEvent) {
  if (event.type === "team_message") {
    return `${event.from ?? "unknown"} → ${event.to ?? "unknown"}: ${event.text ?? ""}`;
  }
  if (event.type === "agent_thought") {
    return `${event.agent ?? "unknown"} thinking: ${event.text ?? ""}`;
  }
  if (event.type === "operator_msg") {
    return `${event.from ?? "unknown"} → ${event.to ?? "unknown"}: ${event.text ?? ""}`;
  }
  if (event.type === "agent_error") {
    return `${event.agent ?? event.from ?? "unknown"}: ${event.text ?? "unknown error"}`;
  }
  if (event.type === "issue_changed") {
    return `issue changed: ${String(event.id ?? event.issue_id ?? "")}`;
  }
  return event.type;
}

function parseToolkits(value: string) {
  return value
    .split(",")
    .map((toolkit) => toolkit.trim())
    .filter(Boolean);
}

export default function AgentTeamWorkspace() {
  const [teams, setTeams] = useState<AgentTeamProject[]>([]);
  const [templates, setTemplates] = useState<AgentTeamTemplate[]>([]);
  const [recovery, setRecovery] = useState<AgentTeamStartupRecovery | null>(null);
  const [settings, setSettings] = useState<AgentTeamSettings | null>(null);
  const [settingsReady, setSettingsReady] = useState(false);
  const [selectedTeamId, setSelectedTeamId] = useState<string | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [pulse, setPulse] = useState<AgentTeamPulse | null>(null);
  const [members, setMembers] = useState<AgentTeamMember[]>([]);
  const [events, setEvents] = useState<AgentTeamEvent[]>([]);
  const [connectionState, setConnectionState] =
    useState<AgentTeamEventConnectionState>("connecting");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [newTeamId, setNewTeamId] = useState("");
  const [newTeamName, setNewTeamName] = useState("");
  const [newTeamTemplate, setNewTeamTemplate] = useState("");
  const [newTeamRepo, setNewTeamRepo] = useState("");
  const [settingsStrongModel, setSettingsStrongModel] = useState("");
  const [settingsMainModel, setSettingsMainModel] = useState("");
  const [settingsCheapModel, setSettingsCheapModel] = useState("");
  const [settingsBaseUrl, setSettingsBaseUrl] = useState("");
  const [settingsScoutInterval, setSettingsScoutInterval] = useState("0");
  const [settingsApiKey, setSettingsApiKey] = useState("");
  const [messageText, setMessageText] = useState("");
  const [messageTarget, setMessageTarget] = useState("team");
  const [memberDraft, setMemberDraft] = useState<AgentTeamMemberDraft | null>(null);
  const [newMember, setNewMember] = useState({
    id: "",
    persona: "",
    role_label: "",
    model: "main",
    toolkits: "",
  });
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const selectedTeam = useMemo(
    () => teams.find((team) => team.id === selectedTeamId) ?? null,
    [teams, selectedTeamId]
  );

  const selectedMember = useMemo(
    () => members.find((member) => member.id === selectedAgentId) ?? null,
    [members, selectedAgentId]
  );

  const pulseByAgentId = useMemo(
    () => new Map((pulse?.agents ?? []).map((agent) => [agent.id, agent])),
    [pulse]
  );

  const loadTeams = useCallback(async () => {
    try {
      const [{ projects }, { templates }, { recovery }] = await Promise.all([
        api.listAgentTeams(),
        api.listAgentTeamTemplates(),
        api.getAgentTeamStartup(),
      ]);
      setTeams(projects);
      setTemplates(templates);
      setRecovery(recovery);
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error));
    } finally {
      setSettingsReady(true);
    }
  }, []);

  const loadSettings = useCallback(async () => {
    try {
      const loadedSettings = await api.getAgentTeamSettings();
      setSettings(loadedSettings);
      setSettingsStrongModel(loadedSettings.models.strong);
      setSettingsMainModel(loadedSettings.models.main);
      setSettingsCheapModel(loadedSettings.models.cheap);
      setSettingsBaseUrl(loadedSettings.base_url);
      setSettingsScoutInterval(String(loadedSettings.scout_interval_secs));
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error));
    }
  }, []);

  useEffect(() => {
    void loadTeams();
    void loadSettings();
  }, [loadTeams, loadSettings]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      void loadTeams();
    }, 15000);
    return () => window.clearInterval(interval);
  }, [loadTeams]);

  const loadPulse = useCallback(async (teamId: string) => {
    try {
      setPulse(await api.getAgentTeamPulse(teamId));
      setActionError(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  }, []);

  const loadMembers = useCallback(async (teamId: string) => {
    try {
      const loadedMembers = await api.listAgentTeamMembers(teamId);
      setMembers(loadedMembers.members);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  }, []);

  useEffect(() => {
    if (!selectedTeamId) {
      setPulse(null);
      setMembers([]);
      return;
    }
    void loadPulse(selectedTeamId);
    void loadMembers(selectedTeamId);
    const interval = window.setInterval(() => {
      void loadPulse(selectedTeamId);
    }, 5000);
    return () => window.clearInterval(interval);
  }, [loadMembers, loadPulse, selectedTeamId]);

  useEffect(() => {
    const connection = connectAgentTeamEvents({
      onEvent: (event) => {
        setEvents((previous) => [...previous, event].slice(-500));
        if (event.type === "issue_changed") {
          void loadTeams();
        }
      },
      onStateChange: setConnectionState,
    });
    return () => connection.close();
  }, [loadTeams]);

  useEffect(() => {
    setMemberDraft(
      selectedMember
        ? { ...selectedMember, toolkits: selectedMember.toolkits.join(", ") }
        : null
    );
  }, [selectedMember]);

  useEffect(() => {
    if (
      messageTarget !== "team" &&
      !members.some((member) => member.id === messageTarget)
    ) {
      setMessageTarget("team");
    }
  }, [members, messageTarget]);

  const conversationEvents = useMemo(() => {
    if (!selectedTeamId) return [];
    const broadcastIds = new Set<string>();
    return events.filter((event) => {
      if (event.project && event.project !== selectedTeamId) return false;
      if (event.type !== "team_message" && event.type !== "agent_thought") {
        return false;
      }
      if (
        event.type === "team_message" &&
        typeof event.broadcast_id === "string" &&
        event.broadcast_id
      ) {
        if (broadcastIds.has(event.broadcast_id)) return false;
        broadcastIds.add(event.broadcast_id);
      }
      return true;
    });
  }, [events, selectedTeamId]);

  const otherEvents = useMemo(
    () =>
      events.filter(
        (event) =>
          (!event.project || event.project === selectedTeamId) &&
          event.type !== "team_message" &&
          event.type !== "agent_thought"
      ),
    [events, selectedTeamId]
  );

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ block: "end" });
  }, [conversationEvents.length]);

  const selectTeam = (teamId: string) => {
    setSelectedTeamId(teamId);
    setSelectedAgentId(null);
    setMemberDraft(null);
    setMessageTarget("team");
    setMessageText("");
  };

  const createTeam = async () => {
    const id = newTeamId.trim();
    if (!TEAM_ID_PATTERN.test(id)) {
      setActionError("团队 ID 必须以字母或数字开头，只能包含字母、数字、下划线和连字符。");
      return;
    }
    setBusyAction("create");
    try {
      await api.createAgentTeam({
        id,
        name: newTeamName.trim() || undefined,
        template_id: newTeamTemplate || undefined,
        repo_path: newTeamRepo.trim() || undefined,
      });
      setNewTeamId("");
      setNewTeamName("");
      setNewTeamRepo("");
      await loadTeams();
      selectTeam(id);
      setActionError(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  };

  const saveSettings = async () => {
    if (!settingsStrongModel.trim() || !settingsMainModel.trim()) {
      setActionError("strong 和 main 模型 ID 不能为空。");
      return;
    }
    setBusyAction("settings");
    try {
      const scoutInterval = Number.parseInt(settingsScoutInterval, 10);
      if (!Number.isSafeInteger(scoutInterval) || scoutInterval < 0) {
        setActionError("Scout 间隔必须是非负整数。");
        return;
      }
      await api.updateAgentTeamSettings({
        strong: settingsStrongModel.trim(),
        main: settingsMainModel.trim(),
        cheap: settingsCheapModel.trim(),
        scout_interval_secs: scoutInterval,
        base_url: settingsBaseUrl.trim(),
        api_key: settingsApiKey.trim() || undefined,
      });
      setSettingsApiKey("");
      await loadSettings();
      setActionError(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  };

  const restartTeam = async (teamId: string) => {
    if (!window.confirm(`重启团队 ${teamId}？未完成的 inbox/timer 会恢复到一致状态。`)) return;
    setBusyAction(`restart:${teamId}`);
    try {
      await api.restartAgentTeam(teamId);
      await loadTeams();
      await loadPulse(teamId);
      setActionError(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  };

  const deleteTeam = async (teamId: string) => {
    if (!window.confirm(`删除团队 ${teamId}？团队配置将从运行时移除。`)) return;
    setBusyAction(`delete:${teamId}`);
    try {
      await api.deleteAgentTeam(teamId);
      await loadTeams();
      if (selectedTeamId === teamId) {
        setSelectedTeamId(null);
        setSelectedAgentId(null);
        setPulse(null);
      }
      setActionError(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  };

  const addMember = async () => {
    if (!selectedTeamId) return;
    const id = newMember.id.trim();
    if (!TEAM_ID_PATTERN.test(id)) {
      setActionError("成员 ID 必须以字母或数字开头，只能包含字母、数字、下划线和连字符。");
      return;
    }
    if (!newMember.persona.trim()) {
      setActionError("成员 persona 不能为空。");
      return;
    }
    setBusyAction("add-member");
    try {
      await api.addAgentTeamMember(selectedTeamId, {
        id,
        persona: newMember.persona.trim(),
        role_label: newMember.role_label.trim() || id,
        model: newMember.model.trim() || "main",
        toolkits: parseToolkits(newMember.toolkits),
      });
      setNewMember({
        id: "",
        persona: "",
        role_label: "",
        model: "main",
        toolkits: "",
      });
      await Promise.all([loadMembers(selectedTeamId), loadPulse(selectedTeamId)]);
      setSelectedAgentId(id);
      setMessageTarget(id);
      setActionError(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  };

  const saveMember = async () => {
    if (!selectedTeamId || !memberDraft) return;
    if (!memberDraft.persona.trim()) {
      setActionError("成员 persona 不能为空。");
      return;
    }
    setBusyAction(`save-member:${memberDraft.id}`);
    try {
      await api.updateAgentTeamMember(selectedTeamId, memberDraft.id, {
        persona: memberDraft.persona,
        role_label: memberDraft.role_label,
        model: memberDraft.model,
        toolkits: parseToolkits(memberDraft.toolkits),
      });
      await Promise.all([loadMembers(selectedTeamId), loadPulse(selectedTeamId)]);
      setActionError(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  };

  const deleteMember = async (memberId: string) => {
    if (!selectedTeamId) return;
    if (!window.confirm(`删除成员 ${memberId}？运行时会立即停止它并更新 team.json。`)) {
      return;
    }
    setBusyAction(`delete-member:${memberId}`);
    try {
      await api.deleteAgentTeamMember(selectedTeamId, memberId);
      if (selectedAgentId === memberId) {
        setSelectedAgentId(null);
        setMessageTarget("team");
      }
      await Promise.all([loadMembers(selectedTeamId), loadPulse(selectedTeamId)]);
      setActionError(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  };

  const sendMessage = async () => {
    if (!selectedTeamId || !messageTarget || !messageText.trim()) return;
    setBusyAction("send");
    try {
      await api.sendAgentTeamMessage(
        selectedTeamId,
        messageTarget,
        messageText.trim()
      );
      setMessageText("");
      setActionError(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-1 gap-4 p-4">
      <aside className="flex w-80 min-w-0 flex-col gap-3 overflow-y-auto rounded-xl border border-gray-200 bg-white p-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-700">Agent Teams</h2>
          <p className="mt-1 text-xs text-gray-500">
            通过 runtime local API 管理团队；浏览器不接触 runtime token。
          </p>
        </div>
        <section
          className="rounded-lg border border-gray-200 p-3"
          data-testid="agent-team-runtime-settings"
          data-ready={settingsReady ? "true" : "false"}
        >
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Runtime 设置
          </h3>
          <div className="mt-2 space-y-2">
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
              placeholder={
                settings?.api_key_set ? "已设置（输入替换）" : "API key"
              }
              aria-label="AgentTeam API key"
              disabled={!settingsReady || busyAction === "settings"}
              autoComplete="new-password"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
            <button
              onClick={saveSettings}
              disabled={!settingsReady || busyAction === "settings"}
              className="w-full rounded-lg border border-blue-500 px-3 py-2 text-sm font-medium text-blue-600 hover:bg-blue-50 disabled:opacity-50"
            >
              保存 Runtime 设置
            </button>
          </div>
        </section>
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
                {template.name} ({template.id})
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
            onClick={createTeam}
            disabled={busyAction === "create"}
            className="w-full rounded-lg bg-blue-500 px-3 py-2 text-sm font-medium text-white hover:bg-blue-600 disabled:opacity-50"
          >
            创建团队
          </button>
        </div>
        <div className="space-y-2" data-testid="agent-team-list">
          {teams.length === 0 && (
            <p className="rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-500">暂无团队</p>
          )}
          {teams.map((team) => (
            <div
              key={team.id}
              className={`rounded-lg border p-3 ${
                team.id === selectedTeamId
                  ? "border-blue-400 bg-blue-50"
                  : "border-gray-200 hover:bg-gray-50"
              }`}
            >
              <button
                onClick={() => selectTeam(team.id)}
                className="w-full text-left text-sm font-medium text-gray-800"
              >
                {team.id}
              </button>
              <p className="mt-1 truncate text-xs text-gray-500" title={team.repo_path ?? ""}>
                {team.repo_path ?? "runtime 数据目录"}
              </p>
              <div className="mt-2 flex gap-2">
                <button
                  data-testid="agent-team-restart"
                  onClick={() => restartTeam(team.id)}
                  disabled={busyAction === `restart:${team.id}`}
                  className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100 disabled:opacity-50"
                >
                  重启
                </button>
                <button
                  onClick={() => deleteTeam(team.id)}
                  disabled={busyAction === `delete:${team.id}`}
                  className="rounded border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50 disabled:opacity-50"
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col gap-4 overflow-hidden">
        {recovery?.status === "degraded" && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
            <strong>启动降级：</strong>已恢复 {recovery.restored_teams}/
            {recovery.persisted_teams} 个团队。
            {recovery.failed_teams.length > 0 && (
              <ul className="mt-2 list-disc pl-5">
                {recovery.failed_teams.map((failure) => (
                  <li key={`${failure.team_id}:${failure.reason}`}>
                    {failure.team_id}: {RECOVERY_REASONS[failure.reason] ?? failure.reason} —{" "}
                    {failure.detail}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {(loadError || actionError) && (
          <div
            className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-700"
            data-testid="agent-team-action-error"
            role="alert"
          >
            {loadError ?? actionError}
          </div>
        )}

        {!selectedTeam ? (
          <div className="flex flex-1 items-center justify-center rounded-xl border border-dashed border-gray-300 bg-white text-sm text-gray-500">
            选择或创建一个团队
          </div>
        ) : (
          <div className="grid min-h-0 flex-1 grid-cols-[minmax(280px,340px)_minmax(360px,1fr)_minmax(260px,340px)] gap-4">
            <section className="min-h-0 overflow-y-auto rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-gray-700">成员</h2>
                <button
                  onClick={() => void loadPulse(selectedTeam.id)}
                  className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100"
                >
                  刷新
                </button>
              </div>
              <form className="mt-3 space-y-2" data-testid="agent-team-add-member">
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
                  rows={3}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                />
                <input
                  value={newMember.role_label}
                  onChange={(event) =>
                    setNewMember((current) => ({ ...current, role_label: event.target.value }))
                  }
                  placeholder="角色标签（默认使用 ID）"
                  aria-label="新成员角色标签"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                />
                <input
                  value={newMember.model}
                  onChange={(event) =>
                    setNewMember((current) => ({ ...current, model: event.target.value }))
                  }
                  placeholder="模型（strong/main/cheap）"
                  aria-label="新成员模型"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                />
                <input
                  value={newMember.toolkits}
                  onChange={(event) =>
                    setNewMember((current) => ({ ...current, toolkits: event.target.value }))
                  }
                  placeholder="工具包，逗号分隔"
                  aria-label="新成员工具包"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                />
                <button
                  type="button"
                  onClick={addMember}
                  disabled={busyAction === "add-member"}
                  className="w-full rounded-lg bg-blue-500 px-3 py-2 text-sm font-medium text-white hover:bg-blue-600 disabled:opacity-50"
                >
                  添加成员
                </button>
              </form>

              <div className="mt-4 space-y-2" data-testid="agent-team-members">
                {members.map((member) => {
                  const agent = pulseByAgentId.get(member.id);
                  return (
                    <div
                      key={member.id}
                      className={`rounded-lg border ${
                        member.id === selectedAgentId
                          ? "border-blue-400 bg-blue-50"
                          : "border-gray-200 bg-white"
                      }`}
                    >
                      <button
                        onClick={() => setSelectedAgentId(member.id)}
                        className="w-full p-3 text-left hover:bg-gray-50"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium text-gray-800">{member.id}</span>
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs ${agentStatusClass(
                              agent?.status ?? "unknown"
                            )}`}
                          >
                            {agent?.status ?? "unknown"}
                          </span>
                        </div>
                        <p className="mt-1 truncate text-xs text-gray-500" title={member.persona}>
                          {member.persona || "未设置 persona"}
                        </p>
                        <p className="mt-1 text-xs text-gray-400">
                          {[member.role_label, member.model, member.toolkits.join(", ")]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                        {(agent?.phase || agent?.activity?.task) && (
                          <p className="mt-1 truncate text-xs text-gray-500">
                            {[agent?.phase, agent?.activity?.task].filter(Boolean).join(" · ")}
                          </p>
                        )}
                        {agent?.error && (
                          <p className="mt-1 text-xs text-red-600">{agent.error}</p>
                        )}
                      </button>
                      <div className="border-t border-gray-100 px-3 py-2">
                        <button
                          onClick={() => deleteMember(member.id)}
                          disabled={busyAction === `delete-member:${member.id}`}
                          className="rounded border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50 disabled:opacity-50"
                        >
                          删除成员
                        </button>
                      </div>
                    </div>
                  );
                })}
                {members.length === 0 && (
                  <p className="rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-500">
                    团队没有成员
                  </p>
                )}
              </div>

              {memberDraft && (
                <form className="mt-4 space-y-2" data-testid="agent-team-edit-member">
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
                    rows={4}
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
                  <input
                    value={memberDraft.model}
                    onChange={(event) =>
                      setMemberDraft((current) =>
                        current ? { ...current, model: event.target.value } : current
                      )
                    }
                    placeholder="模型（strong/main/cheap）"
                    aria-label="成员模型"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                  />
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
                      onClick={saveMember}
                      disabled={busyAction === `save-member:${memberDraft.id}`}
                      className="flex-1 rounded-lg bg-blue-500 px-3 py-2 text-sm font-medium text-white hover:bg-blue-600 disabled:opacity-50"
                    >
                      保存成员
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteMember(memberDraft.id)}
                      disabled={busyAction === `delete-member:${memberDraft.id}`}
                      className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-600 hover:bg-red-50 disabled:opacity-50"
                    >
                      删除
                    </button>
                  </div>
                </form>
              )}
            </section>

            <section className="flex min-h-0 flex-col rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-gray-700">共享聊天与思考</h2>
                <span className="text-xs text-gray-500" data-testid="agent-team-connection">
                  {connectionState === "open" ? "已连接" : connectionState}
                </span>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-gray-200 bg-white p-4">
                <div className="space-y-3" data-testid="agent-team-conversation">
                  {conversationEvents.length === 0 && (
                    <p className="text-sm text-gray-500">暂无聊天或思考过程</p>
                  )}
                  {conversationEvents.map((event, index) =>
                    event.type === "team_message" ? (
                      <article
                        key={`${event.type}:${event.message_id ?? event.broadcast_id ?? index}`}
                        className="rounded-lg border border-gray-200 bg-gray-50 p-3"
                      >
                        <div className="flex items-center justify-between gap-2 text-xs text-gray-500">
                          <span className="font-medium text-gray-700">
                            {event.from ?? "unknown"} → {event.to ?? "unknown"}
                          </span>
                          <span>{event.message_type ?? "message"}</span>
                        </div>
                        <p className="mt-2 whitespace-pre-wrap text-sm text-gray-800">
                          {event.text ?? ""}
                        </p>
                      </article>
                    ) : (
                      <article
                        key={`${event.type}:${event.message_id ?? index}`}
                        className="rounded-lg border border-violet-200 bg-violet-50 p-3"
                      >
                        <div className="flex items-center justify-between gap-2 text-xs text-violet-700">
                          <span className="font-medium">{event.agent ?? "unknown"} 思考</span>
                          <span>thinking</span>
                        </div>
                        <p className="mt-2 whitespace-pre-wrap text-sm text-violet-900">
                          {event.text ?? ""}
                        </p>
                      </article>
                    )
                  )}
                  <div ref={chatEndRef} />
                </div>
              </div>

              <div className="mt-4 space-y-2">
                <select
                  value={messageTarget}
                  onChange={(event) => setMessageTarget(event.target.value)}
                  aria-label="消息目标"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                >
                  <option value="team">发给整个团队</option>
                  {members.map((member) => (
                    <option key={member.id} value={member.id}>
                      发给 {member.id}
                    </option>
                  ))}
                </select>
                <textarea
                  value={messageText}
                  onChange={(event) => setMessageText(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void sendMessage();
                    }
                  }}
                  placeholder="输入消息；Enter 发送，Shift+Enter 换行"
                  aria-label="团队消息"
                  rows={3}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                />
                <button
                  onClick={sendMessage}
                  disabled={busyAction === "send" || !messageText.trim()}
                  className="w-full rounded-lg bg-blue-500 px-4 py-2 text-sm font-medium text-white hover:bg-blue-600 disabled:opacity-50"
                >
                  发送
                </button>
              </div>
            </section>

            <section className="flex min-h-0 flex-col gap-4">
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-xl border border-gray-200 bg-white p-3">
                  <p className="text-xs text-gray-500">待处理消息</p>
                  <p className="mt-1 text-xl font-semibold text-gray-800">
                    {pulse?.pending.length ?? 0}
                  </p>
                </div>
                <div className="rounded-xl border border-gray-200 bg-white p-3">
                  <p className="text-xs text-gray-500">待确认 issue</p>
                  <p className="mt-1 text-xl font-semibold text-gray-800">
                    {pulse?.issues.pending ?? 0}
                  </p>
                </div>
                <div className="rounded-xl border border-gray-200 bg-white p-3">
                  <p className="text-xs text-gray-500">活跃定时器</p>
                  <p className="mt-1 text-xl font-semibold text-gray-800">
                    {pulse?.timers.pending ?? 0}
                  </p>
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-gray-200 bg-white p-4">
                <h2 className="text-sm font-semibold text-gray-700">其它事件</h2>
                <div className="mt-3 space-y-2" data-testid="agent-team-events">
                  {otherEvents.length === 0 && (
                    <p className="text-sm text-gray-500">暂无事件</p>
                  )}
                  {otherEvents.map((event, index) => (
                    <p
                      key={`${event.type}:${index}`}
                      className="rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-700"
                    >
                      {eventSummary(event)}
                    </p>
                  ))}
                </div>
              </div>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
