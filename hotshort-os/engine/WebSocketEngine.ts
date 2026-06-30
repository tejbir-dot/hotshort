import eventBus from "./EventBus";

type Message = {
  event: string;
  payload?: Record<string, unknown>;
};

class WebSocketEngine {
  private socket: WebSocket | null = null;

  private reconnectTimer: number | null = null;

  private reconnectDelay = 2000;

  connect(url: string) {
    if (this.socket) return;

    this.socket = new WebSocket(url);

    this.socket.onopen = () => {
      console.log("🟢 HotShort Connected");

      eventBus.emit("SYSTEM_READY");
    };

    this.socket.onmessage = (message) => {
      try {
        const data: Message = JSON.parse(message.data);

        eventBus.emit(
          data.event as any,
          data.payload
        );
      } catch (err) {
        console.error(err);
      }
    };

    this.socket.onclose = () => {
      console.log("🔴 Disconnected");

      this.socket = null;

      this.reconnect();
    };

    this.socket.onerror = () => {
      this.socket?.close();
    };
  }

  send(event: string, payload?: unknown) {
    if (!this.socket) return;

    this.socket.send(
      JSON.stringify({
        event,
        payload,
      })
    );
  }

  disconnect() {
    this.socket?.close();

    this.socket = null;
  }

  private reconnect() {
    if (this.reconnectTimer) return;

    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;

      this.connect(
        process.env.NEXT_PUBLIC_WS ??
          "ws://localhost:5000/ws"
      );
    }, this.reconnectDelay);
  }
}

const websocketEngine = new WebSocketEngine();

export default websocketEngine;