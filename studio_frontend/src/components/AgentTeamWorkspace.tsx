import { useAgentTeamWorkspace } from "../hooks/useAgentTeamWorkspace";
import AgentTeamSidebar from "./agentTeam/AgentTeamSidebar";
import AgentTeamChatPanel from "./agentTeam/AgentTeamChatPanel";
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
  return (
    <div className="flex h-full min-h-0 flex-1 overflow-hidden">
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

      {selectedTeam && (
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
      )}

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
