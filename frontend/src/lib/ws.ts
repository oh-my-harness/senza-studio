import type { StudioEvent } from '../types';

export class WsClient {
  private ws: WebSocket | null = null;
  private onEvent: (event: StudioEvent) => void;

  constructor(url: string, onEvent: (event: StudioEvent) => void) {
    this.onEvent = onEvent;
    this.ws = new WebSocket(url);
    this.ws.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data);
        this.onEvent(event);
      } catch {
        // ignore non-JSON messages
      }
    };
  }

  send(text: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(text);
    }
  }

  sendJson(data: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  close() {
    this.ws?.close();
    this.ws = null;
  }
}
