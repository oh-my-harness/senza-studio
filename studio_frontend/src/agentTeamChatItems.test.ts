import { describe, expect, it } from "vitest";
import { buildAgentTeamChatItems } from "./agentTeamChatItems";
import type { AgentTeamEvent } from "./agentTeamEvents";

function chatMessage(overrides: Partial<AgentTeamEvent> = {}): AgentTeamEvent {
  return {
    type: "team_message",
    message_id: "message-1",
    conversation: "team",
    view_kind: "group_message",
    from: "operator",
    text: "hello",
    ...overrides,
  };
}

describe("buildAgentTeamChatItems", () => {
  it("keeps chat messages only for the active conversation", () => {
    const items = buildAgentTeamChatItems(
      [
        chatMessage({ message_id: "group" }),
        chatMessage({
          message_id: "direct",
          conversation: "scout",
          view_kind: "direct_message",
        }),
      ],
      "team",
      "all"
    );

    expect(items.map((item) => item.key)).toEqual(["group"]);
  });

  it("folds consecutive thoughts and repeated errors", () => {
    const items = buildAgentTeamChatItems(
      [
        { type: "agent_thought", agent: "scout", text: "A" },
        { type: "agent_thought", agent: "scout", text: "B" },
        { type: "agent_thought", agent: "judge", text: "C" },
        { type: "agent_error", agent: "scout", text: "timeout" },
        { type: "agent_error", agent: "scout", text: "timeout" },
      ],
      "team",
      "all"
    );

    expect(items.map(({ kind, from, text, count }) => ({ kind, from, text, count }))).toEqual([
      { kind: "thought", from: "scout", text: "AB", count: undefined },
      { kind: "thought", from: "judge", text: "C", count: undefined },
      { kind: "system", from: "scout", text: "timeout", count: 2 },
    ]);
  });

  it("applies sender filters", () => {
    const items = buildAgentTeamChatItems(
      [
        chatMessage({ message_id: "operator-message" }),
        chatMessage({
          message_id: "member-message",
          from: "scout",
          view_kind: "group_reply",
        }),
      ],
      "team",
      "scout"
    );

    expect(items.map((item) => item.from)).toEqual(["scout"]);
  });
});
