import animationClock from "./AnimationClock";
import nodeRegistry, { NodeStatus, NeuralNode } from "./NodeRegistry";
import eventBus from "./EventBus";

export interface NodeAnimState {
  id: string;
  scale: number;
  glowIntensity: number;
  color: string;
  ringIntensity: number;
  particleCount: number;
  status: NodeStatus;
}

const STATUS_TARGETS: Record<
  NodeStatus,
  Omit<NodeAnimState, "id" | "status">
> = {
  idle: {
    scale: 1,
    glowIntensity: 0.18,
    color: "#FFE08A",
    ringIntensity: 0.2,
    particleCount: 2,
  },
  thinking: {
    scale: 1.06,
    glowIntensity: 0.5,
    color: "#59B7FF",
    ringIntensity: 0.55,
    particleCount: 8,
  },
  processing: {
    scale: 1.12,
    glowIntensity: 0.85,
    color: "#FFE08A",
    ringIntensity: 0.9,
    particleCount: 16,
  },
  success: {
    scale: 1.08,
    glowIntensity: 0.65,
    color: "#6BE6FF",
    ringIntensity: 0.6,
    particleCount: 10,
  },
  warning: {
    scale: 0.96,
    glowIntensity: 0.35,
    color: "#FF8A52",
    ringIntensity: 0.3,
    particleCount: 4,
  },
};

const LERP_SPEED = 4.5; // units per second

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

function hexToRgb(hex: string) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return { r, g, b };
}

function lerpColor(a: string, b: string, t: number) {
  const ca = hexToRgb(a);
  const cb = hexToRgb(b);
  const r = Math.round(lerp(ca.r, cb.r, t));
  const g = Math.round(lerp(ca.g, cb.g, t));
  const bl = Math.round(lerp(ca.b, cb.b, t));
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${bl.toString(16).padStart(2, "0")}`;
}

class NodeAnimationEngine {
  private states = new Map<string, NodeAnimState>();
  private listeners = new Set<(states: Map<string, NodeAnimState>) => void>();

  constructor() {
    nodeRegistry.subscribe(this.onNodesUpdate);
    animationClock.subscribe(this.update);

    eventBus.on("WHISPER_STARTED", () => {
      nodeRegistry.update("Whisper", { status: "thinking" });
    });
    eventBus.on("TRANSCRIPT_READY", () => {
      nodeRegistry.success("Whisper");
      nodeRegistry.update("Semantic", { status: "processing" });
    });
    eventBus.on("HOOK_DETECTED", () => {
      nodeRegistry.success("Semantic");
      nodeRegistry.update("Hook", { status: "processing" });
    });
    eventBus.on("RANKING_UPDATED", () => {
      nodeRegistry.success("Hook");
      nodeRegistry.update("Ranking", { status: "processing" });
    });
    eventBus.on("EDITOR_STARTED", () => {
      nodeRegistry.success("Ranking");
      nodeRegistry.update("Editor", { status: "processing" });
    });
    eventBus.on("RENDER_STARTED", () => {
      nodeRegistry.success("Editor");
      nodeRegistry.update("Renderer", { status: "processing" });
    });
    eventBus.on("RENDER_FINISHED", () => {
      nodeRegistry.success("Renderer");
      setTimeout(() => {
        ["Whisper", "Semantic", "Hook", "Ranking", "Editor", "Renderer"].forEach(
          (id) => nodeRegistry.idle(id)
        );
      }, 1800);
    });
  }

  private onNodesUpdate = (nodes: NeuralNode[]) => {
    nodes.forEach((node) => {
      if (!this.states.has(node.id)) {
        const target = STATUS_TARGETS[node.status];
        this.states.set(node.id, {
          id: node.id,
          status: node.status,
          ...target,
        });
      } else {
        const existing = this.states.get(node.id)!;
        existing.status = node.status;
      }
    });
  };

  private update = (_: number, delta: number) => {
    const dt = Math.min(delta / 1000, 0.1);
    const t = Math.min(LERP_SPEED * dt, 1);

    let changed = false;
    this.states.forEach((state) => {
      const target = STATUS_TARGETS[state.status];
      const newScale = lerp(state.scale, target.scale, t);
      const newGlow = lerp(state.glowIntensity, target.glowIntensity, t);
      const newRing = lerp(state.ringIntensity, target.ringIntensity, t);
      const newParticles = lerp(state.particleCount, target.particleCount, t);
      const newColor = lerpColor(state.color, target.color, t * 0.5);

      if (
        Math.abs(newScale - state.scale) > 0.0001 ||
        Math.abs(newGlow - state.glowIntensity) > 0.0001
      ) {
        changed = true;
      }

      state.scale = newScale;
      state.glowIntensity = newGlow;
      state.ringIntensity = newRing;
      state.particleCount = newParticles;
      state.color = newColor;
    });

    if (changed) this.notify();
  };

  getState(id: string): NodeAnimState | undefined {
    return this.states.get(id);
  }

  getAll(): Map<string, NodeAnimState> {
    return this.states;
  }

  subscribe(callback: (states: Map<string, NodeAnimState>) => void) {
    this.listeners.add(callback);
    callback(new Map(this.states));
    return () => this.listeners.delete(callback);
  }

  private notify() {
    const snapshot = new Map(this.states);
    this.listeners.forEach((l) => l(snapshot));
  }
}

const nodeAnimationEngine = new NodeAnimationEngine();

export default nodeAnimationEngine;
