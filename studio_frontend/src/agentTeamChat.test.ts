import { describe, expect, it } from "vitest";
import type { AgentTeamEvent } from "./agentTeamEvents";
import {
  chatMessagesForConversation,
  chatMessageKey,
  deleteProjectChatMessages,
  isAgentTeamChatMessage,
  upsertChatMessages,
  type AgentTeamChatMessage,
} from "./agentTeamChat";

function message(overrides: Partial<AgentTeamEvent> = {}): AgentTeamEvent {
  return {
    type: "team_message",
    message_id: "message-1",
    conversation: "team",
    view_kind: "group_message",
    ...overrides,
  };
}

describe("agent team chat contract", () => {
  it("deduplicates by the server-provided logical message id", () => {
    const first = message({ text: "same text" });
    const second = message({ text: "same text" });
    expect(chatMessageKey(first as AgentTeamChatMessage)).toBe(
      chatMessageKey(second as AgentTeamChatMessage)
    );
  });

  it("rejects messages without a complete server chat contract", () => {
    expect(isAgentTeamChatMessage(message({ message_id: undefined }))).toBe(false);
    expect(isAgentTeamChatMessage(message({ conversation: undefined }))).toBe(false);
    const legacy = {
      ...message(),
      view_kind: "legacy" as unknown as AgentTeamEvent["view_kind"],
    };
    expect(isAgentTeamChatMessage(legacy)).toBe(false);
  });

  it("orders durable history by server sequence instead of arrival order", () => {
    const incoming = [
      message({ sequence: 3, created_at: "2026-01-01T00:00:03Z" }),
      message({
        message_id: "message-2",
        sequence: 1,
        created_at: "2026-01-01T00:00:01Z",
      }),
    ] as AgentTeamChatMessage[];
    const store = upsertChatMessages(new Map(), "p1", "team", incoming);
    const ordered = chatMessagesForConversation(store, "p1", "team");
    expect(ordered.map((item) => item.sequence)).toEqual([1, 3]);
  });

  it("isolates projects and deletes their durable conversations together", () => {
    const teamMessage = message({ sequence: 1 }) as AgentTeamChatMessage;
    let store = upsertChatMessages(new Map(), "p1", "team", [teamMessage]);
    store = upsertChatMessages(store, "p2", "team", [
      message({ message_id: "message-2", sequence: 1 }) as AgentTeamChatMessage,
    ]);
    store = deleteProjectChatMessages(store, "p1");

    expect(chatMessagesForConversation(store, "p1", "team")).toHaveLength(0);
    expect(chatMessagesForConversation(store, "p2", "team")).toHaveLength(1);
  });
});
