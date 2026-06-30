import animationClock from "./AnimationClock";
import nodeAnimationEngine from "./NodeAnimationEngine";
import reactorEngine from "./ReactorEngine";
import rippleEngine from "./RippleEngine";
import scannerEngine from "./ScannerEngine";

export interface GlowState {
  intensity: number;     // 0-1
  radius: number;        // px
  color: string;
  bloom: number;         // blur px
}

class GlowEngine {
  private nodeGlow = new Map<string, GlowState>();
  private listeners = new Set<(map: Map<string, GlowState>) => void>();
  private scannerActive: string | null = null;

  constructor() {
    scannerEngine.subscribe((state) => {
      this.scannerActive = state.activeNodeId;
    });

    animationClock.subscribe(this.update);
  }

  private update = () => {
    const reactorState = reactorEngine.getState();
    const animStates = nodeAnimationEngine.getAll();
    const ripples = rippleEngine.getRipples();

    animStates.forEach((anim, id) => {
      const isScanned = this.scannerActive === id;
      const hasRipple = ripples.some((r) => r.nodeId === id);

      const scannerBoost = isScanned ? 0.3 : 0;
      const rippleBoost = hasRipple ? 0.2 : 0;
      const reactorBoost = reactorState.energy * 0.15;

      const intensity = Math.min(
        anim.glowIntensity + scannerBoost + rippleBoost + reactorBoost,
        1
      );

      const radius = 40 + intensity * 120;
      const bloom = 18 + intensity * 60;

      this.nodeGlow.set(id, {
        intensity,
        radius,
        color: anim.color,
        bloom,
      });
    });

    this.notify();
  };

  getGlow(nodeId: string): GlowState {
    return (
      this.nodeGlow.get(nodeId) ?? {
        intensity: 0.18,
        radius: 40,
        color: "#FFE08A",
        bloom: 18,
      }
    );
  }

  getAll() {
    return new Map(this.nodeGlow);
  }

  subscribe(callback: (map: Map<string, GlowState>) => void) {
    this.listeners.add(callback);
    callback(new Map(this.nodeGlow));
    return () => this.listeners.delete(callback);
  }

  private notify() {
    const snapshot = new Map(this.nodeGlow);
    this.listeners.forEach((l) => l(snapshot));
  }
}

const glowEngine = new GlowEngine();

export default glowEngine;
