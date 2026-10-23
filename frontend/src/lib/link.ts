// The single live connection to the Jarvis server. Reconnects on its own.
export type ServerMsg = { type: string; [key: string]: any };
type Handler = (msg: ServerMsg) => void;
type StatusHandler = (online: boolean) => void;

class Link {
  private ws: WebSocket | null = null;
  private handlers = new Set<Handler>();
  private statusHandlers = new Set<StatusHandler>();
  private retry = 0;
  online = false;

  connect() {
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return; // already connecting/open
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.setOnline(true);
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") return;
      try {
        const msg = JSON.parse(ev.data) as ServerMsg;
        this.handlers.forEach((h) => h(msg));
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = () => {
      this.setOnline(false);
      const delay = Math.min(8000, 800 * 2 ** this.retry++);
      setTimeout(() => this.connect(), delay);
    };
  }

  private setOnline(v: boolean) {
    this.online = v;
    this.statusHandlers.forEach((h) => h(v));
  }

  on(h: Handler) {
    this.handlers.add(h);
    return () => this.handlers.delete(h);
  }

  onStatus(h: StatusHandler) {
    this.statusHandlers.add(h);
    return () => this.statusHandlers.delete(h);
  }

  send(msg: object) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  sendAudio(buf: ArrayBuffer) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(buf);
  }
}

export const link = new Link();
