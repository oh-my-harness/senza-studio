export interface AgentTeamEvent {
  type: string;
  project?: string;
  from?: string;
  to?: string;
  agent?: string;
  text?: string;
  message_type?: string;
  message_id?: string;
  broadcast_id?: string | null;
  [key: string]: unknown;
}

export type AgentTeamEventConnectionState = "connecting" | "open" | "reconnecting";

export function parseAgentTeamEvent(value: unknown): AgentTeamEvent | null {
  if (typeof value !== "object" || value === null) return null;
  const event = value as Record<string, unknown>;
  return typeof event.type === "string" ? (event as AgentTeamEvent) : null;
}

export function createAgentTeamWebSocket(): WebSocket {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return new WebSocket(`${protocol}//${location.host}/ws/team`);
}

export function connectAgentTeamEvents(options: {
  createSocket?: () => WebSocket;
  onEvent: (event: AgentTeamEvent) => void;
  onStateChange?: (state: AgentTeamEventConnectionState) => void;
  reconnectDelayMs?: number;
}) {
  const createSocket = options.createSocket ?? createAgentTeamWebSocket;
  const reconnectDelayMs = options.reconnectDelayMs ?? 3000;
  let closed = false;
  let socket: WebSocket | null = null;
  let reconnectTimer: number | null = null;

  const clearReconnectTimer = () => {
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const connect = () => {
    if (closed) return;
    options.onStateChange?.("connecting");
    socket = createSocket();
    socket.onopen = () => {
      if (closed) return;
      options.onStateChange?.("open");
    };
    socket.onmessage = (message) => {
      if (closed) return;
      try {
        const event = parseAgentTeamEvent(JSON.parse(String(message.data)));
        if (event) options.onEvent(event);
      } catch {
      }
    };
    socket.onclose = () => {
      if (closed) return;
      options.onStateChange?.("reconnecting");
      reconnectTimer = window.setTimeout(connect, reconnectDelayMs);
    };
    socket.onerror = () => {
      socket?.close();
    };
  };

  connect();

  return {
    close() {
      closed = true;
      clearReconnectTimer();
      socket?.close();
      socket = null;
    },
  };
}
