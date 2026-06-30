import animationClock from "./AnimationClock";
import eventBus from "./EventBus";

export interface Packet {
  id: string;

  from: string;

  to: string;

  progress: number;

  speed: number;

  color: string;

  size: number;
}

class PacketEngine {
  private packets: Packet[] = [];

  private listeners = new Set<
    (packets: Packet[]) => void
  >();

  constructor() {
    animationClock.subscribe(this.update);

    eventBus.on("PACKET_SENT", (payload) => {
      this.spawn({
        from: String(payload?.from ?? "Core"),
        to: String(payload?.to ?? "Unknown"),
        color: String(payload?.color ?? "#FFE08A"),
      });
    });
  }

  subscribe(
    callback: (packets: Packet[]) => void
  ) {
    this.listeners.add(callback);

    callback([...this.packets]);

    return () => this.listeners.delete(callback);
  }

  private notify() {
    const snapshot = [...this.packets];

    this.listeners.forEach((listener) =>
      listener(snapshot)
    );
  }

  spawn({
    from,
    to,
    color,
  }: {
    from: string;
    to: string;
    color: string;
  }) {
    this.packets.push({
      id: crypto.randomUUID(),

      from,

      to,

      progress: 0,

      speed: 0.55 + Math.random() * 0.45,

      color,

      size: 3 + Math.random() * 2,
    });

    this.notify();
  }

  clear() {
    this.packets = [];

    this.notify();
  }

  getPackets() {
    return [...this.packets];
  }

  private update = (
    _: number,
    delta: number
  ) => {
    const dt = delta / 1000;

    this.packets.forEach((packet) => {
      packet.progress += packet.speed * dt;
    });

    this.packets = this.packets.filter(
      (packet) => packet.progress < 1
    );

    this.notify();
  };
}

const packetEngine = new PacketEngine();

export default packetEngine;