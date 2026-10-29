import { useMemo } from "react";
import { Group, Panel, useGroupRef, usePanelRef } from "react-resizable-panels";
import { useAgentTeamWorkspace } from "../hooks/useAgentTeamWorkspace";
import AgentTeamSidebar from "./agentTeam/AgentTeamSidebar";
import AgentTeamChatPanel from "./agentTeam/AgentTeamChatPanel";
import PanelDock from "../panels/PanelDock";
import PanelFrame from "../panels/PanelFrame";
import PanelSeparator from "../panels/PanelSeparator";
import { STUDIO_PANEL_SPECS, panelResizeBehavior, type StudioPanelId } from "../panels/panelLayout";
import { useStudioPanelLayout } from "../panels/useStudioPanelLayout";
import {
  AgentTeamNewTeamModal,
  AgentTeamSettingsModal,
  AgentTeamMembersModal,
} from "./agentTeam/AgentTeamModals";

export default function AgentTeamWorkspace() {
  const workspace = useAgentTeamWorkspace();
  const {
    teams,
    selectedTeamId,
    selectedTeam,
    activeConversation,
    recovery,
    pulse,
    templates,
    settings,
    settingsReady,
    members,
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
  } = workspace;

  const groupRef = useGroupRef();
  const sidebarRef = usePanelRef();
  const chatRef = usePanelRef();
  const agentPanelIds: StudioPanelId[] = ["agent-sidebar", "agent-chat"];
  const agentGroupRefs = useMemo(() => ({ agent: groupRef }), [groupRef]);
  const agentPanelRefs = useMemo(
    () => ({ "agent-sidebar": sidebarRef, "agent-chat": chatRef }),
    [sidebarRef, chatRef],
  );
  const panelLayout = useStudioPanelLayout({
    scope: "agent-team",
    groupRefs: agentGroupRefs,
    panelRefs: agentPanelRefs,
    available: agentPanelIds,
  });
  const agentFocusFallback = (id: StudioPanelId) => {
    if (panelLayout.isMinimized(id)) return `dock-restore-${id}`;
    if (panelLayout.maximized && panelLayout.maximized !== id) {
      return `panel-maximize-${panelLayout.maximized}`;
    }
    return undefined;
  };

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
      <PanelDock
        panels={panelLayout.minimized.map((id) => STUDIO_PANEL_SPECS[id])}
        onRestore={panelLayout.restore}
      />
      <div className="flex min-h-0 flex-1 overflow-x-auto overflow-y-hidden">
        <Group
          id="agent-team-panels"
          groupRef={groupRef}
          orientation="horizontal"
          className="h-full w-full shrink-0"
          style={{
            minWidth:
              panelLayout.maximized && STUDIO_PANEL_SPECS[panelLayout.maximized].group === "agent"
                ? 0
                : Math.max(panelLayout.groupMinSpan("agent", agentPanelIds), 1140),
          }}
          defaultLayout={panelLayout.defaultLayout(
            "agent",
            agentPanelIds,
            "horizontal",
            1140,
            "agent-spacer",
          )}
          onLayoutChange={(next) => panelLayout.onLayoutChange("agent", next)}
          onLayoutChanged={(next, meta) => panelLayout.onLayoutChanged("agent", next, meta)}
          resizeTargetMinimumSize={{ fine: 12, coarse: 24 }}
        >
          <Panel
            id="agent-sidebar"
            panelRef={sidebarRef}
            groupResizeBehavior={panelResizeBehavior("preserve-pixel-size", {
              hidden: panelLayout.isHidden("agent-sidebar"),
              maximized: panelLayout.maximized === "agent-sidebar",
            })}
            defaultSize={STUDIO_PANEL_SPECS["agent-sidebar"].minWidth}
            minSize={STUDIO_PANEL_SPECS["agent-sidebar"].minWidth}
            collapsible
            collapsedSize={0}
            disabled={panelLayout.isHidden("agent-sidebar")}
          >
            <PanelFrame
              id="agent-sidebar"
              title={STUDIO_PANEL_SPECS["agent-sidebar"].title}
              minimized={panelLayout.isMinimized("agent-sidebar")}
              hidden={panelLayout.isHidden("agent-sidebar")}
              maximized={panelLayout.maximized === "agent-sidebar"}
              focusFallbackId={agentFocusFallback("agent-sidebar")}
              contentMinWidth={STUDIO_PANEL_SPECS["agent-sidebar"].contentMinWidth}
              contentMinHeight={STUDIO_PANEL_SPECS["agent-sidebar"].contentMinHeight}
              onMinimize={() => panelLayout.minimize("agent-sidebar")}
              onToggleMaximize={() => panelLayout.toggleMaximize("agent-sidebar")}
            >
              <AgentTeamSidebar
                teams={teams}
                selectedTeamId={selectedTeamId}
                selectedTeam={selectedTeam}
                activeConversation={activeConversation}
                conversationList={conversationList}
                recovery={recovery}
                members={members.length}
                selectTeam={selectTeam}
                selectConversation={selectConversation}
                loadPulse={loadPulse}
                onOpenNewTeam={() => setShowNewTeamModal(true)}
                onOpenSettings={() => setShowSettingsModal(true)}
                onOpenMembers={() => setShowMembersModal(true)}
              />
            </PanelFrame>
          </Panel>
          <PanelSeparator
            orientation="horizontal"
            label="调整 Agent Team 侧栏宽度"
            hidden={panelLayout.isHidden("agent-sidebar") || panelLayout.isHidden("agent-chat")}
          />
          <Panel
            id="agent-chat"
            panelRef={chatRef}
            groupResizeBehavior={panelResizeBehavior("preserve-relative-size", {
              hidden: panelLayout.isHidden("agent-chat"),
              maximized: panelLayout.maximized === "agent-chat",
            })}
            defaultSize={STUDIO_PANEL_SPECS["agent-chat"].minWidth}
            minSize={STUDIO_PANEL_SPECS["agent-chat"].minWidth}
            collapsible
            collapsedSize={0}
            disabled={panelLayout.isHidden("agent-chat")}
          >
            <PanelFrame
              id="agent-chat"
              title={STUDIO_PANEL_SPECS["agent-chat"].title}
              minimized={panelLayout.isMinimized("agent-chat")}
              hidden={panelLayout.isHidden("agent-chat")}
              maximized={panelLayout.maximized === "agent-chat"}
              focusFallbackId={agentFocusFallback("agent-chat")}
              contentMinWidth={STUDIO_PANEL_SPECS["agent-chat"].contentMinWidth}
              contentMinHeight={STUDIO_PANEL_SPECS["agent-chat"].contentMinHeight}
              onMinimize={() => panelLayout.minimize("agent-chat")}
              onToggleMaximize={() => panelLayout.toggleMaximize("agent-chat")}
            >
              {selectedTeam ? (
                <AgentTeamChatPanel
                  selectedTeam={selectedTeam}
                  activeConversation={activeConversation}
                  activeMember={activeMember}
                  members={members}
                  pulse={pulse}
                  pulseByAgentId={pulseByAgentId}
                  memberById={memberById}
                  connectionState={connectionState}
                  loadError={loadError}
                  actionError={actionError}
                  actionNotice={actionNotice}
                  busyAction={busyAction}
                  chatEndRef={chatEndRef}
                  chatItems={chatItems}
                  chatFilter={chatFilter}
                  setChatFilter={setChatFilter}
                  showMentionMenu={showMentionMenu}
                  setShowMentionMenu={setShowMentionMenu}
                  messageText={messageText}
                  setMessageText={setMessageText}
                  onRestartTeam={restartTeam}
                  onDeleteTeam={deleteTeam}
                  onAbort={abortActive}
                  onSendMessage={() => void sendMessage()}
                />
              ) : (
                <div className="flex h-full items-center justify-center p-6 text-sm text-gray-400">
                  选择或创建一个团队后开始对话
                </div>
              )}
            </PanelFrame>
          </Panel>
          <Panel
            id="agent-spacer"
            groupResizeBehavior="preserve-pixel-size"
            defaultSize={0}
            minSize={0}
            collapsible
            collapsedSize={0}
            disabled
            aria-hidden="true"
            data-testid="panel-spacer-agent"
            className="pointer-events-none"
          >
            <div className="pointer-events-none h-full w-full" />
          </Panel>
        </Group>
      </div>

      <AgentTeamNewTeamModal
        open={showNewTeamModal}
        error={actionError ?? loadError}
        newTeamId={newTeamId}
        setNewTeamId={setNewTeamId}
        newTeamName={newTeamName}
        setNewTeamName={setNewTeamName}
        newTeamTemplate={newTeamTemplate}
        setNewTeamTemplate={setNewTeamTemplate}
        newTeamRepo={newTeamRepo}
        setNewTeamRepo={setNewTeamRepo}
        templates={templates}
        busyAction={busyAction}
        onCreateTeam={() => void createTeam()}
        onClose={() => setShowNewTeamModal(false)}
      />

      <AgentTeamSettingsModal
        open={showSettingsModal}
        error={actionError ?? loadError}
        settings={settings}
        settingsReady={settingsReady}
        busyAction={busyAction}
        settingsStrongModel={settingsStrongModel}
        setSettingsStrongModel={setSettingsStrongModel}
        settingsMainModel={settingsMainModel}
        setSettingsMainModel={setSettingsMainModel}
        settingsCheapModel={settingsCheapModel}
        setSettingsCheapModel={setSettingsCheapModel}
        settingsBaseUrl={settingsBaseUrl}
        setSettingsBaseUrl={setSettingsBaseUrl}
        settingsScoutInterval={settingsScoutInterval}
        setSettingsScoutInterval={setSettingsScoutInterval}
        settingsApiKey={settingsApiKey}
        setSettingsApiKey={setSettingsApiKey}
        onSaveSettings={() => void saveSettings()}
        onClose={() => setShowSettingsModal(false)}
      />

      <AgentTeamMembersModal
        open={showMembersModal}
        error={actionError ?? loadError}
        selectedTeam={selectedTeam}
        members={members}
        pulseByAgentId={pulseByAgentId}
        memberDraft={memberDraft}
        setMemberDraft={setMemberDraft}
        newMember={newMember}
        setNewMember={setNewMember}
        busyAction={busyAction}
        onSaveMember={() => void saveMember()}
        onAddMember={() => void addMember()}
        onDeleteMember={deleteMember}
        onClose={() => setShowMembersModal(false)}
      />
    </div>
  );
}
