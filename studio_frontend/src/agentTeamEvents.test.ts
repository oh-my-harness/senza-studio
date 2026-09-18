import { afterEach, describe, expect, it, vi } from "vitest";
import {
  connectAgentTeamEvents,
  parseAgentTeamEvent,
} from "./agentTeamEvents";

class FakeWebSocket {
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  close() {
    this.onclose?.();
  }
}

describe("parseAgentTeamEvent", () => {
  it("accepts objects with a string type", () => {
    expect(parseAgentTeamEvent({ type: "operator_msg", text: "hello" })).toEqual({
      type: "operator_msg",
      text: "hello",
    });
  });

  it("rejects malformed events", () => {
    expect(parseAgentTeamEvent(null)).toBeNull();
    expect(parseAgentTeamEvent("operator_msg")).toBeNull();
    expect(parseAgentTeamEvent({ text: "missing type" })).toBeNull();
  });
});

describe("connectAgentTeamEvents", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("emits valid events and reconnects after the socket closes", () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", globalThis);
    const sockets: FakeWebSocket[] = [];
    const states: string[] = [];
    const events: unknown[] = [];

    const connection = connectAgentTeamEvents({
      createSocket: () => {
        const socket = new FakeWebSocket();
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      onEvent: (event) => events.push(event),
      onStateChange: (state) => states.push(state),
      reconnectDelayMs: 10,
    });

    expect(sockets).toHaveLength(1);
    sockets[0].onopen?.();
    sockets[0].onmessage?.({ data: JSON.stringify({ type: "operator_msg" }) });
    sockets[0].onmessage?.({ data: "not-json" });
    sockets[0].onmessage?.({ data: JSON.stringify({ text: "invalid" }) });
    sockets[0].close();

    expect(events).toEqual([{ type: "operator_msg" }]);
    expect(states).toEqual(["connecting", "open", "reconnecting"]);

    vi.advanceTimersByTime(10);
    expect(sockets).toHaveLength(2);
    sockets[1].onopen?.();
    expect(states).toEqual(["connecting", "open", "reconnecting", "connecting", "open"]);

    connection.close();
    vi.advanceTimersByTime(10);
    expect(sockets).toHaveLength(2);
  });
});
