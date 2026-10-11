import { describe, expect, it } from "vitest";
import { isAgentTeamChatMessage } from "./agentTeamChat";
import type { AgentTeamEvent } from "./agentTeamEvents";
import {
  clearUnreadConversation,
  deleteProjectUnread,
  deserializeUnreadStore,
  serializeUnreadStore,
  trackUnreadMessages,
  unreadCount,
} from "./agentTeamUnread";

function message(overrides: Partial<AgentTeamEvent> = {}) {
  return {
    type: "team_message",
    message_id: "message-1",
    conversation: "team",
    view_kind: "group_message",
    ...overrides,
  } as AgentTeamEvent;
}

function tracked(event: AgentTeamEvent) {
  if (!isAgentTeamChatMessage(event)) throw new Error("invalid chat message");
  return event;
}

describe("agent team unread state", () => {
  it("tracks only agent replies and deduplicates server message ids", () => {
    let store = trackUnreadMessages(new Map(), "team-1", [
      tracked(message({ from: "agent", text: "first" })),
      tracked(message({ from: "agent", text: "duplicate delivery" })),
      tracked(message({ from: "operator", text: "ignored" })),
    ]);
    store = trackUnreadMessages(store, "team-1", [
      tracked(message({ message_id: "message-2", from: "agent" })),
    ]);

    expect(unreadCount(store, "team-1", "team")).toBe(2);
  });

  it("clears a conversation or a whole project without affecting others", () => {
    let store = trackUnreadMessages(new Map(), "team-1", [
      tracked(message({ from: "agent" })),
    ]);
    store = trackUnreadMessages(store, "team-1", [
      tracked(message({ message_id: "message-2", from: "agent", conversation: "planner" })),
    ]);
    store = trackUnreadMessages(store, "team-2", [
      tracked(message({ message_id: "message-3", from: "agent" })),
    ]);

    store = clearUnreadConversation(store, "team-1", "team");
    expect(unreadCount(store, "team-1", "team")).toBe(0);
    expect(unreadCount(store, "team-1", "planner")).toBe(1);
    expect(unreadCount(store, "team-2", "team")).toBe(1);

    store = deleteProjectUnread(store, "team-1");
    expect(unreadCount(store, "team-1", "planner")).toBe(0);
    expect(unreadCount(store, "team-2", "team")).toBe(1);
  });

  it("round-trips durable unread ids safely", () => {
    const store = trackUnreadMessages(new Map(), "team-1", [
      tracked(message({ from: "agent" })),
    ]);

    const restored = deserializeUnreadStore(serializeUnreadStore(store));
    expect(unreadCount(restored, "team-1", "team")).toBe(1);
    expect(deserializeUnreadStore("not-json").size).toBe(0);
  });
});
