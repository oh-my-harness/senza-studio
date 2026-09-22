import type { AgentTeamEvent } from "./agentTeamEvents";

export const OPERATOR_ID = "operator";
export const TEAM_CONVERSATION_ID = "team";

export type AgentTeamChatMessage = AgentTeamEvent & {
  message_id: string;
  conversation: string;
  view_kind: "group_message" | "group_reply" | "direct_message";
};

export function isAgentTeamChatMessage(
  event: AgentTeamEvent
): event is AgentTeamChatMessage {
  return (
    event.type === "team_message" &&
    typeof event.message_id === "string" &&
    event.message_id.length > 0 &&
    typeof event.conversation === "string" &&
    event.conversation.length > 0 &&
    (event.view_kind === "group_message" ||
      event.view_kind === "group_reply" ||
      event.view_kind === "direct_message")
  );
}

export function chatMessageKey(event: AgentTeamChatMessage) {
  return event.message_id;
}

export type ChatStore = Map<string, AgentTeamChatMessage[]>;

export function emptyChatStore(): ChatStore {
  return new Map();
}

export function chatStoreKey(project: string, conversation: string) {
  return `${project}\u0000${conversation}`;
}

export function chatMessagesForConversation(
  store: ChatStore,
  project: string | null,
  conversation: string
): AgentTeamChatMessage[] {
  if (!project) return [];
  return store.get(chatStoreKey(project, conversation)) ?? [];
}

function chatSortKey(message: AgentTeamChatMessage) {
  const sequence =
    typeof message.sequence === "number" && Number.isFinite(message.sequence)
      ? message.sequence
      : null;
  const createdAt = message.created_at ?? message.ts;
  return [sequence, createdAt, message.message_id] as const;
}

function compareChatMessages(
  left: AgentTeamChatMessage,
  right: AgentTeamChatMessage
) {
  const leftKey = chatSortKey(left);
  const rightKey = chatSortKey(right);
  const leftSequence = leftKey[0] ?? Number.MAX_SAFE_INTEGER;
  const rightSequence = rightKey[0] ?? Number.MAX_SAFE_INTEGER;
  if (leftSequence !== rightSequence) return leftSequence - rightSequence;
  const leftTime = leftKey[1] ?? "";
  const rightTime = rightKey[1] ?? "";
  if (leftTime !== rightTime) return leftTime < rightTime ? -1 : 1;
  return leftKey[2].localeCompare(rightKey[2]);
}

function upsertConversation(
  store: ChatStore,
  key: string,
  incoming: AgentTeamChatMessage[],
  limit = 500
) {
  const merged = new Map<string, AgentTeamChatMessage>();
  for (const message of [...(store.get(key) ?? []), ...incoming]) {
    merged.set(message.message_id, message);
  }
  const messages = [...merged.values()]
    .sort(compareChatMessages)
    .slice(-limit);
  const next = new Map(store);
  next.set(key, messages);
  return next;
}

export function upsertChatMessages(
  store: ChatStore,
  project: string,
  conversation: string,
  incoming: AgentTeamEvent[],
  limit = 500
): ChatStore {
  const messages = incoming.filter((event) => {
    if (event.project && event.project !== project) return false;
    return isAgentTeamChatMessage(event);
  }) as AgentTeamChatMessage[];
  if (messages.length === 0) return store;
  return upsertConversation(store, chatStoreKey(project, conversation), messages, limit);
}

export function deleteProjectChatMessages(
  store: ChatStore,
  project: string
): ChatStore {
  const prefix = `${project}\u0000`;
  const next = new Map(store);
  for (const key of next.keys()) {
    if (key.startsWith(prefix)) next.delete(key);
  }
  return next;
}
