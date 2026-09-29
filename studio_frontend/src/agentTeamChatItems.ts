import {
  chatMessageKey,
  isAgentTeamChatMessage,
  OPERATOR_ID,
  type AgentTeamChatMessage,
} from "./agentTeamChat";
import type { AgentTeamEvent } from "./agentTeamEvents";

export interface AgentTeamChatItem {
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

function eventTime(event: AgentTeamEvent) {
  return typeof event.ts === "string" ? event.ts : undefined;
}

function formatTime(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function isAgentOwnedItem(
  event: AgentTeamEvent,
  activeConversation: string
) {
  return (
    activeConversation === "team" || event.agent === activeConversation
  );
}

export function buildAgentTeamChatItems(
  events: AgentTeamEvent[],
  activeConversation: string,
  chatFilter: string
): AgentTeamChatItem[] {
  const items: AgentTeamChatItem[] = [];

  for (const event of events) {
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
      continue;
    }

    if (event.type === "agent_thought") {
      if (!isAgentOwnedItem(event, activeConversation)) continue;
      const last = items[items.length - 1];
      const from = event.agent ?? "unknown";
      if (last && last.kind === "thought" && last.from === from) {
        last.text += event.text ?? "";
      } else {
        items.push({
          key: `thought:${from}:${items.length}`,
          kind: "thought",
          from,
          text: event.text ?? "",
          mine: false,
          time: formatTime(eventTime(event)),
        });
      }
      continue;
    }

    if (event.type !== "agent_error") continue;
    if (!isAgentOwnedItem(event, activeConversation)) continue;
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

  return chatFilter === "all"
    ? items
    : items.filter((item) => item.from === chatFilter);
}
