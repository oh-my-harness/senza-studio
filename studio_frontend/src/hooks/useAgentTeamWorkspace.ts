import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import {
  chatMessagesForConversation,
  isAgentTeamChatMessage,
  deleteProjectChatMessages,
  emptyChatStore,
  TEAM_CONVERSATION_ID,
  upsertChatMessages,
  type ChatStore,
} from "../agentTeamChat";
import { buildAgentTeamChatItems, type AgentTeamChatItem } from "../agentTeamChatItems";
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

export type AgentTeamMemberDraft = Omit<AgentTeamMember, "toolkits"> & {
  toolkits: string;
};

export interface ConversationItem {
  id: string;
  name: string;
  preview?: string;
  persona?: string;
  status?: string;
}

function parseToolkits(value: string) {
  return value
    .split(",")
    .map((toolkit) => toolkit.trim())
    .filter(Boolean);
}

export function useAgentTeamWorkspace() {
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

  const chatItems = useMemo<AgentTeamChatItem[]>(
    () =>
      selectedTeamId
        ? buildAgentTeamChatItems(conversationEvents, activeConversation, chatFilter)
        : [],
    [conversationEvents, selectedTeamId, activeConversation, chatFilter]
  );

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

  const selectTeam = useCallback((teamId: string) => {
    setSelectedTeamId(teamId);
    setActiveConversation("team");
    setMemberDraft(null);
    setMessageText("");
  }, []);

  const selectConversation = useCallback((conversationId: string) => {
    setActiveConversation(conversationId);
    setMessageText("");
  }, []);

  const abortActive = useCallback(async () => {
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
  }, [selectedTeam, activeConversation, loadPulse]);

  const createTeam = useCallback(async () => {
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
      setSelectedTeamId(id);
      setActiveConversation(TEAM_CONVERSATION_ID);
      setActionError(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  }, [newTeamId, newTeamName, newTeamTemplate, newTeamRepo, loadTeams]);

  const saveSettings = useCallback(async () => {
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
  }, [
    settingsStrongModel,
    settingsMainModel,
    settingsCheapModel,
    settingsScoutInterval,
    settingsBaseUrl,
    settingsApiKey,
    loadSettings,
  ]);

  const restartTeam = useCallback(async (teamId: string) => {
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
  }, [loadTeams, loadPulse]);

  const deleteTeam = useCallback(async (teamId: string) => {
    if (!window.confirm(`删除团队 ${teamId}？聊天、issues、memory 和 sessions 都会删除。`)) return;
    setBusyAction(`delete:${teamId}`);
    try {
      await api.deleteAgentTeam(teamId);
      setEvents((previous) => previous.filter((event) => event.project !== teamId));
      setChatStore((previous) => deleteProjectChatMessages(previous, teamId));
      await loadTeams();
      setSelectedTeamId((current) => (current === teamId ? null : current));
      setActiveConversation(TEAM_CONVERSATION_ID);
      setActionError(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  }, [loadTeams]);

  const addMember = useCallback(async () => {
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
  }, [selectedTeamId, newMember, loadMembers, loadPulse]);

  const saveMember = useCallback(async () => {
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
  }, [selectedTeamId, memberDraft, loadMembers, loadPulse]);

  const deleteMember = useCallback(async (memberId: string) => {
    if (!selectedTeamId) return;
    if (!window.confirm(`删除成员 ${memberId}？运行时会立即停止它并更新 team.json。`)) {
      return;
    }
    setBusyAction(`delete-member:${memberId}`);
    try {
      await api.deleteAgentTeamMember(selectedTeamId, memberId);
      setActiveConversation((current) => (current === memberId ? TEAM_CONVERSATION_ID : current));
      setMemberDraft((current) => (current?.id === memberId ? null : current));
      await Promise.all([loadMembers(selectedTeamId), loadPulse(selectedTeamId)]);
      setActionError(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  }, [selectedTeamId, loadMembers, loadPulse]);

  const sendMessage = useCallback(async () => {
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
  }, [selectedTeamId, messageText, activeConversation]);

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
      setActiveConversation(TEAM_CONVERSATION_ID);
    }
  }, [members, activeConversation, selectedTeamId]);

  return {
    teams,
    templates,
    recovery,
    settings,
    settingsReady,
    selectedTeamId,
    selectedTeam,
    activeConversation,
    members,
    pulse,
    pulseByAgentId,
    memberById,
    connectionState,
    loadError,
    actionError,
    actionNotice,
    busyAction,
    newTeamId,
    setNewTeamId,
    newTeamName,
    setNewTeamName,
    newTeamTemplate,
    setNewTeamTemplate,
    newTeamRepo,
    setNewTeamRepo,
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
    messageText,
    setMessageText,
    chatFilter,
    setChatFilter,
    memberDraft,
    setMemberDraft,
    newMember,
    setNewMember,
    showNewTeamModal,
    setShowNewTeamModal,
    showMembersModal,
    setShowMembersModal,
    showSettingsModal,
    setShowSettingsModal,
    showMentionMenu,
    setShowMentionMenu,
    chatEndRef,
    chatItems,
    conversationList,
    activeMember,
    loadPulse,
    selectTeam,
    selectConversation,
    abortActive,
    createTeam,
    saveSettings,
    restartTeam,
    deleteTeam,
    addMember,
    saveMember,
    deleteMember,
    sendMessage,
  };
}
