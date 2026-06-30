import animationClock from "./AnimationClock";
import eventBus from "./EventBus";
import nodeRegistry from "./NodeRegistry";
import graphLayout from "./GraphLayout";

export interface Ripple {
  id: string;
  nodeId: string;
  x: number;
  y: number;
  radius: number;
  maxRadius: number;
  opacity: number;
  color: string;
  startTime: number;
  duration: number;
}

class RippleEngine {
  private ripples: Ripple[] = [];
  private listeners = new Set<(ripples: Ripple[]) => void>();
  private startTime = performance.now();

  constructor() {
    animationClock.subscribe(this.update);

    eventBus.on("CORE_PULSE", (payload) => {
      const strength = Number(payload?.strength ?? 0.5);
      this.spawnAt("Core", strength * 180, "#FFE08A", 1200);
    });

    eventBus.on("NODE_ACTIVE", (payload) => {
      const id = String(payload?.id ?? "Core");
      this.spawnAt(id, 80, "#59B7FF", 900);
    });

    eventBus.on("PACKET_SENT", (payload) => {
      const to = String(payload?.to ?? "Core");
      this.spawnAt(to, 55, "#FFE08A", 700);
    });

    eventBus.on("HOOK_DETECTED", () => {
      this.spawnAt("Hook", 120, "#FFE08A", 1400);
    });

    eventBus.on("RENDER_FINISHED", () => {
      this.spawnAt("Core", 160, "#FFFFFF", 1600);
    });
  }

  spawnAt(
    nodeId: string,
    maxRadius = 80,
    color = "#FFE08A",
    duration = 900
  ) {
    const point = graphLayout.getNode(nodeId);
    if (!point) return;

    // Convert from graph-local coords to screen center
    const x = 320 + point.x;
    const y = 320 + point.y;

    this.ripples.push({
      id: crypto.randomUUID(),
      nodeId,
      x,
      y,
      radius: 0,
      maxRadius,
      opacity: 0.85,
      color,
      startTime: performance.now() - this.startTime,
      duration,
    });

    this.notify();
  }

  private update = () => {
    const now = performance.now() - this.startTime;

    this.ripples.forEach((r) => {
      const elapsed = now - r.startTime;
      const t = Math.min(elapsed / r.duration, 1);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out-cubic
      r.radius = eased * r.maxRadius;
      r.opacity = (1 - t) * 0.75;
    });

    this.ripples = this.ripples.filter((r) => {
      const elapsed = now - r.startTime;
      return elapsed < r.duration;
    });

    this.notify();
  };

  subscribe(callback: (ripples: Ripple[]) => void) {
    this.listeners.add(callback);
    callback([...this.ripples]);
    return () => this.listeners.delete(callback);
  }

  private notify() {
    const snapshot = [...this.ripples];
    this.listeners.forEach((l) => l(snapshot));
  }

  getRipples() {
    return [...this.ripples];
  }
}

const rippleEngine = new RippleEngine();

export default rippleEngine;
