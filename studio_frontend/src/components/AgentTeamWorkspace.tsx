import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import {
  chatMessagesForConversation,
  chatMessageKey,
  deleteProjectChatMessages,
  isAgentTeamChatMessage,
  emptyChatStore,
  OPERATOR_ID,
  TEAM_CONVERSATION_ID,
  upsertChatMessages,
  type ChatStore,
} from "../agentTeamChat";
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

const MEMBER_MODEL_OPTIONS = ["strong", "main", "cheap"];

function agentStatusClass(status: string) {
  if (status === "busy") return "bg-amber-100 text-amber-800";
  if (status === "error" || status === "failed") return "bg-red-100 text-red-700";
  if (status === "idle" || status === "ready") return "bg-emerald-100 text-emerald-800";
  return "bg-gray-100 text-gray-700";
}

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

function formatTime(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function parseToolkits(value: string) {
  return value
    .split(",")
    .map((toolkit) => toolkit.trim())
    .filter(Boolean);
}

interface ChatItem {
  key: string;
  kind: "message" | "thought" | "system";
  from: string;
  to?: string;
  text: string;
  mine: boolean;
  messageType?: string;
  time?: string;
  count?: number;
}

interface ConversationItem {
  id: string;
  name: string;
  preview?: string;
  persona?: string;
  status?: string;
}

function eventTime(event: AgentTeamEvent) {
  return typeof event.ts === "string" ? event.ts : undefined;
}

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
}export default function AgentTeamWorkspace() {
  const [teams, setTeams] = useState<AgentTeamProject[]>([]);
  const [templates, setTemplates] = useState<AgentTeamTemplate[]>([]);
  const [recovery, setRecovery] = useState<AgentTeamStartupRecovery | null>(null);
  const [settings, setSettings] = useState<AgentTeamSettings | null>(null);
  const [settingsReady, setSettingsReady] = useState(false);
  const [selectedTeamId, setSelectedTeamId] = useState<string | null>(null);
  const [activeConversation, setActiveConversation] =
    useState<string>(TEAM_CONVERSATION_ID);
  const [pulse, setPulse] = useState<AgentTeamPulse | null>(null);
  const [members, setMembers] = useState<AgentTeamMember[]>([]);
  const [events, setEvents] = useState<AgentTeamEvent[]>([]);
  const [chatStore, setChatStore] = useState<ChatStore>(emptyChatStore);
  const [connectionState, setConnectionState] =
    useState<AgentTeamEventConnectionState>("connecting");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
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
  const [chatFilter, setChatFilter] = useState("all");
  const [memberDraft, setMemberDraft] = useState<AgentTeamMemberDraft | null>(null);
  const [newMember, setNewMember] = useState({
    id: "",
    persona: "",
    role_label: "",
    model: "main",
    toolkits: "",
  });
  const [showNewTeamModal, setShowNewTeamModal] = useState(false);
  const [showMembersModal, setShowMembersModal] = useState(false);
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [showMentionMenu, setShowMentionMenu] = useState(false);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const selectedTeam = useMemo(
    () => teams.find((team) => team.id === selectedTeamId) ?? null,
    [teams, selectedTeamId]
  );

  const pulseByAgentId = useMemo(
    () => new Map((pulse?.agents ?? []).map((agent) => [agent.id, agent])),
    [pulse]
  );

  const memberById = useMemo(
    () => new Map(members.map((member) => [member.id, member])),
    [members]
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

  const loadChatHistory = useCallback(
    async (teamId: string, conversation: string) => {
      const agent = conversation === TEAM_CONVERSATION_ID ? "team" : conversation;
      try {
        const { messages } = await api.getAgentTeamChatHistory(teamId, agent, 100);
        setChatStore((previous) =>
          upsertChatMessages(previous, teamId, conversation, messages)
        );
      } catch (error) {
        setLoadError(error instanceof Error ? error.message : String(error));
      }
    },
    []
  );

  useEffect(() => {
    if (!selectedTeamId) {
      setPulse(null);
      setMembers([]);
      setChatStore(emptyChatStore());
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
    if (!selectedTeamId) return;
    void loadChatHistory(selectedTeamId, activeConversation);
    if (connectionState !== "open") return;
    const interval = window.setInterval(() => {
      void loadChatHistory(selectedTeamId, activeConversation);
    }, 30000);
    return () => window.clearInterval(interval);
  }, [
    activeConversation,
    connectionState,
    loadChatHistory,
    selectedTeamId,
  ]);

  useEffect(() => {
    const connection = connectAgentTeamEvents({
      onEvent: (event) => {
        const project = event.project;
        if (event.type === "team_deleted" && project) {
          setEvents((previous) => previous.filter((item) => item.project !== project));
          setChatStore((previous) => deleteProjectChatMessages(previous, project));
          return;
        }
        setEvents((previous) => {
          if (isAgentTeamChatMessage(event)) return previous;
          return [...previous, event].slice(-500);
        });
        if (project && isAgentTeamChatMessage(event)) {
          setChatStore((previous) =>
            upsertChatMessages(previous, project, event.conversation, [event])
          );
        }
        if (event.type === "issue_changed") {
          void loadTeams();
        }
      },
      onStateChange: setConnectionState,
    });
  return () => connection.close();
  }, [loadTeams]);

  const conversationEvents = useMemo<AgentTeamEvent[]>(
    () => [
      ...chatMessagesForConversation(chatStore, selectedTeamId, activeConversation),
      ...events.filter(
        (event) => event.project === selectedTeamId && event.type !== "team_message"
      ),
    ],
    [chatStore, selectedTeamId, activeConversation, events]
  );

  const chatItems = useMemo<ChatItem[]>(() => {
    if (!selectedTeamId) return [];
    const items: ChatItem[] = [];
    for (const event of conversationEvents) {
      if (isAgentTeamChatMessage(event)) {
        if (event.conversation !== activeConversation) continue;
        items.push({
          key: chatMessageKey(event),
          kind: "message",
          from: event.from ?? "unknown",
          to: event.to,
          text: event.text ?? "",
          mine: event.from === OPERATOR_ID,
          messageType: event.message_type,
          time: formatTime(eventTime(event)),
        });
      } else if (event.type === "agent_thought") {
        if (
          activeConversation !== "team" &&
          event.agent !== activeConversation &&
          event.agent !== activeConversation
        ) {
          continue;
        }
        const last = items[items.length - 1];
        if (
          last &&
          last.kind === "thought" &&
          last.from === (event.agent ?? "unknown")
        ) {
          last.text += event.text ?? "";
        } else {
          items.push({
            key: `thought:${event.agent ?? "unknown"}:${items.length}`,
            kind: "thought",
            from: event.agent ?? "unknown",
            text: event.text ?? "",
            mine: false,
            time: formatTime(eventTime(event)),
          });
        }
      } else if (event.type === "agent_error") {
        if (
          activeConversation !== "team" &&
          event.agent !== activeConversation &&
          event.agent !== activeConversation
        ) {
          continue;
        }
        const from = event.agent ?? "unknown";
        const text = event.text ?? "";
        const last = items[items.length - 1];
        if (last && last.kind === "system" && last.from === from && last.text === text) {
          last.count = (last.count ?? 1) + 1;
          last.time = formatTime(eventTime(event));
          continue;
        }
        items.push({
          key: `sys:${from}:${items.length}`,
          kind: "system",
          from,
          text,
          mine: false,
          time: formatTime(eventTime(event)),
          count: 1,
        });
      }
    }
    return chatFilter === "all"
      ? items
      : items.filter((item) => item.from === chatFilter);
  }, [conversationEvents, selectedTeamId, activeConversation, chatFilter]);

  const lastMessages = useMemo(() => {
    const previews = new Map<string, string>();
    for (const [conversationId, messages] of chatStore) {
      const key = conversationId.split("\u0000")[1];
      const last = messages[messages.length - 1];
      if (key && last && last.project === selectedTeamId) {
        previews.set(key, `${last.from ?? "?"}: ${last.text ?? ""}`);
      }
    }
    return previews;
  }, [chatStore, selectedTeamId]);

  const conversationList = useMemo<ConversationItem[]>(() => {
    if (!selectedTeam) return [];
    return [
      {
        id: TEAM_CONVERSATION_ID,
        name: "团队群聊",
        preview: lastMessages.get("team"),
      },
      ...members.map((member) => ({
        id: member.id,
        name: member.role_label || member.id,
        preview: lastMessages.get(member.id),
        persona: member.persona,
        status: pulseByAgentId.get(member.id)?.status,
      })),
    ];
  }, [selectedTeam, members, pulseByAgentId, lastMessages]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ block: "end" });
  }, [chatItems.length]);

  const selectTeam = (teamId: string) => {
    setSelectedTeamId(teamId);
    setActiveConversation("team");
    setMemberDraft(null);
    setMessageText("");
  };

  const selectConversation = (conversationId: string) => {
    setActiveConversation(conversationId);
    setMessageText("");
  };

  const abortActive = async () => {
    if (!selectedTeam) return;
    setBusyAction("abort");
    try {
      const targets = [activeConversation];
      const results = await Promise.all(
        targets.map((target) => api.abortAgentTeam(selectedTeam.id, target))
      );
      setActionError(null);
      const interrupted = results.flatMap((result) => result.interrupted ?? []);
      setActionNotice(
        interrupted.length > 0
          ? `已请求打断：${interrupted.join("、")}`
          : "没有需要打断的运行"
      );
      await loadPulse(selectedTeam.id);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
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
      setShowNewTeamModal(false);
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
    if (!window.confirm(`删除团队 ${teamId}？聊天、issues、memory 和 sessions 都会删除。`)) return;
    setBusyAction(`delete:${teamId}`);
    try {
      await api.deleteAgentTeam(teamId);
      setEvents((previous) => previous.filter((event) => event.project !== teamId));
      setChatStore((previous) => deleteProjectChatMessages(previous, teamId));
      await loadTeams();
      if (selectedTeamId === teamId) {
        setSelectedTeamId(null);
        setActiveConversation("team");
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
      setMemberDraft(null);
      setActiveConversation(id);
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
      setMemberDraft(null);
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
      if (activeConversation === memberId) {
        setActiveConversation("team");
      }
      if (memberDraft?.id === memberId) {
        setMemberDraft(null);
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
    if (!selectedTeamId || !messageText.trim()) return;
    setBusyAction("send");
    try {
      await api.sendAgentTeamMessage(
        selectedTeamId,
        activeConversation,
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

  const activeMember =
    activeConversation !== "team"
      ? members.find((member) => member.id === activeConversation) ?? null
      : null;

  useEffect(() => {
    if (
      activeConversation !== "team" &&
      selectedTeamId &&
      !members.some((member) => member.id === activeConversation)
    ) {
      setActiveConversation("team");
    }
  }, [members, activeConversation, selectedTeamId]);  return (
    <div className="flex h-full min-h-0 flex-1 overflow-hidden">
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
            onClick={() => setShowNewTeamModal(true)}
            title="新建团队"
            aria-label="新建团队"
            className="rounded-lg bg-emerald-500 px-2.5 py-1.5 text-sm font-medium text-white hover:bg-emerald-600"
          >
            ＋
          </button>
          <button
            type="button"
            onClick={() => setShowSettingsModal(true)}
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
                setShowMembersModal(true);
              }}
              className="w-full rounded-lg border border-emerald-500 px-3 py-1.5 text-xs font-medium text-emerald-600 hover:bg-emerald-50"
            >
              成员管理（{members.length}）
            </button>
          </div>
        )}
      </aside>

      <main className="flex min-w-0 flex-1 flex-col bg-[#EDEDED]">
        {!selectedTeam ? (
          <div className="flex flex-1 items-center justify-center text-sm text-gray-500">
            选择或创建一个团队
          </div>
        ) : (
          <>
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
                onClick={() => restartTeam(selectedTeam.id)}
                disabled={busyAction === `restart:${selectedTeam.id}`}
                title={busyAction === `restart:${selectedTeam.id}` ? "重启中" : "重启团队"}
                aria-label="重启团队"
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-emerald-200 text-sm text-emerald-600 hover:bg-emerald-50 disabled:opacity-40"
              >
                {busyAction === `restart:${selectedTeam.id}` ? "…" : "↻"}
              </button>
              <button
                type="button"
                onClick={() => deleteTeam(selectedTeam.id)}
                disabled={busyAction === `delete:${selectedTeam.id}`}
                title={busyAction === `delete:${selectedTeam.id}` ? "删除中" : "删除团队"}
                aria-label="删除团队"
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-red-200 text-sm text-red-600 hover:bg-red-50 disabled:opacity-40"
              >
                {busyAction === `delete:${selectedTeam.id}` ? "…" : "🗑"}
              </button>
              <button
                type="button"
                onClick={abortActive}
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
                      void sendMessage();
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
                  onClick={sendMessage}
                  disabled={busyAction === "send" || !messageText.trim()}
                  className="rounded-lg bg-emerald-500 px-5 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
                >
                  发送
                </button>
              </div>
            </div>
          </>
        )}
      </main>      <Modal
        open={showNewTeamModal}
        error={actionError ?? loadError}
        title="新建团队"
        onClose={() => setShowNewTeamModal(false)}
      >
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
            onClick={createTeam}
            disabled={busyAction === "create"}
            className="w-full rounded-lg bg-emerald-500 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
          >
            创建团队
          </button>
        </div>
      </Modal>

      <Modal
        open={showSettingsModal}
        error={actionError ?? loadError}
        title="Runtime 设置"
        onClose={() => setShowSettingsModal(false)}
      >
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
            onClick={saveSettings}
            disabled={!settingsReady || busyAction === "settings"}
            className="w-full rounded-lg bg-emerald-500 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
          >
            保存 Runtime 设置
          </button>
        </section>
      </Modal>

      <Modal
        open={showMembersModal}
        error={actionError ?? loadError}
        title={`成员管理 · ${selectedTeam?.id ?? ""}`}
        onClose={() => setShowMembersModal(false)}
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
                onClick={saveMember}
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
            onClick={addMember}
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
                  onClick={() => deleteMember(member.id)}
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
    </div>
  );
}
