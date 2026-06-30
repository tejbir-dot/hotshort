export type HotShortEvent =
  | "SYSTEM_READY"
  | "WHISPER_STARTED"
  | "WHISPER_FINISHED"
  | "TRANSCRIPT_READY"
  | "HOOK_DETECTED"
  | "PAYOFF_FOUND"
  | "RANKING_UPDATED"
  | "EDITOR_STARTED"
  | "EDITOR_FINISHED"
  | "RENDER_STARTED"
  | "RENDER_FINISHED"
  | "EXPORT_READY"
  | "NODE_ACTIVE"
  | "NODE_IDLE"
  | "CORE_PULSE"
  | "PACKET_SENT";

export interface EventPayload {
  [key: string]: unknown;
}

type Listener = (payload?: EventPayload) => void;

class EventBus {
  private listeners = new Map<
    HotShortEvent,
    Set<Listener>
  >();

  on(event: HotShortEvent, callback: Listener) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }

    this.listeners.get(event)!.add(callback);

    return () => this.off(event, callback);
  }

  off(event: HotShortEvent, callback: Listener) {
    this.listeners.get(event)?.delete(callback);
  }

  emit(
    event: HotShortEvent,
    payload?: EventPayload
  ) {
    this.listeners
      .get(event)
      ?.forEach((listener) => listener(payload));
  }

  once(
    event: HotShortEvent,
    callback: Listener
  ) {
    const unsubscribe = this.on(
      event,
      (payload) => {
        callback(payload);
        unsubscribe();
      }
    );
  }

  clear() {
    this.listeners.clear();
  }
}

const eventBus = new EventBus();

export default eventBus;