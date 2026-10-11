import {
  OPERATOR_ID,
  type AgentTeamChatMessage,
} from "./agentTeamChat";

export type UnreadStore = Map<string, Set<string>>;

const UNREAD_STORAGE_KEY = "senza.agent-team.unread.v1";
const MAX_UNREAD_IDS_PER_CONVERSATION = 200;

export function unreadStoreKey(project: string, conversation: string) {
  return `${project}\u0000${conversation}`;
}

export function unreadCount(
  store: UnreadStore,
  project: string | null,
  conversation: string
) {
  if (!project) return 0;
  return store.get(unreadStoreKey(project, conversation))?.size ?? 0;
}

function addUnreadMessages(
  store: UnreadStore,
  project: string,
  conversation: string,
  incoming: AgentTeamChatMessage[]
) {
  const messageIds = incoming
    .filter((message) => message.from !== OPERATOR_ID)
    .map((message) => message.message_id);
  if (messageIds.length === 0) return store;

  const key = unreadStoreKey(project, conversation);
  const unreadIds = new Set([...(store.get(key) ?? []), ...messageIds]);
  const cappedIds = [...unreadIds].slice(-MAX_UNREAD_IDS_PER_CONVERSATION);
  const next = new Map(store);
  next.set(key, new Set(cappedIds));
  return next;
}

export function trackUnreadMessages(
  store: UnreadStore,
  project: string,
  incoming: AgentTeamChatMessage[]
) {
  const grouped = new Map<string, AgentTeamChatMessage[]>();
  for (const message of incoming) {
    if (message.from === OPERATOR_ID) continue;
    grouped.set(message.conversation, [
      ...(grouped.get(message.conversation) ?? []),
      message,
    ]);
  }

  let next = store;
  for (const [conversation, messages] of grouped) {
    next = addUnreadMessages(next, project, conversation, messages);
  }
  return next;
}

export function clearUnreadConversation(
  store: UnreadStore,
  project: string | null,
  conversation: string
) {
  if (!project) return store;
  const key = unreadStoreKey(project, conversation);
  if (!store.has(key)) return store;
  const next = new Map(store);
  next.delete(key);
  return next;
}

export function deleteProjectUnread(
  store: UnreadStore,
  project: string
) {
  const prefix = `${project}\u0000`;
  const next = new Map(store);
  for (const key of next.keys()) {
    if (key.startsWith(prefix)) next.delete(key);
  }
  return next;
}

export function serializeUnreadStore(store: UnreadStore) {
  return JSON.stringify(
    [...store].map(([key, messageIds]) => [key, [...messageIds]] as const)
  );
}

export function deserializeUnreadStore(value: string | null): UnreadStore {
  if (!value) return new Map();
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) return new Map();
    const store: UnreadStore = new Map();
    for (const entry of parsed) {
      if (!Array.isArray(entry) || entry.length !== 2) continue;
      const [key, rawMessageIds] = entry;
      if (typeof key !== "string" || !key.includes("\u0000")) continue;
      if (!Array.isArray(rawMessageIds)) continue;
      const messageIds = new Set(
        rawMessageIds.filter((id): id is string => typeof id === "string" && id.length > 0)
      );
      if (messageIds.size === 0) continue;
      store.set(key, new Set([...messageIds].slice(-MAX_UNREAD_IDS_PER_CONVERSATION)));
    }
    return store;
  } catch {
    return new Map();
  }
}

export function loadUnreadStore(storage?: Pick<Storage, "getItem">) {
  const selectedStorage =
    storage ?? (typeof window === "undefined" ? undefined : window.localStorage);
  try {
    return deserializeUnreadStore(selectedStorage?.getItem(UNREAD_STORAGE_KEY) ?? null);
  } catch {
    return new Map();
  }
}

export function saveUnreadStore(
  store: UnreadStore,
  storage?: Pick<Storage, "setItem">
) {
  const selectedStorage =
    storage ?? (typeof window === "undefined" ? undefined : window.localStorage);
  try {
    selectedStorage?.setItem(UNREAD_STORAGE_KEY, serializeUnreadStore(store));
  } catch {
  }
}
