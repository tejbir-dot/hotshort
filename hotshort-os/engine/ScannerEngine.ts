import animationClock from "./AnimationClock";
import graphLayout from "./GraphLayout";
import nodeRegistry from "./NodeRegistry";

export interface ScannerState {
  angle: number;       // degrees, 0-360
  x: number;          // beam tip X in graph space (640x640 SVG)
  y: number;
  activeNodeId: string | null;
}

const BEAM_RADIUS = 320; // half the SVG canvas
const RPM = 8;           // rotations per minute

class ScannerEngine {
  private angle = -90; // start at top
  private listeners = new Set<(state: ScannerState) => void>();

  constructor() {
    animationClock.subscribe(this.update);
  }

  private update = (_: number, delta: number) => {
    const dt = Math.min(delta / 1000, 0.1);
    this.angle = (this.angle + (RPM / 60) * 360 * dt) % 360;

    const rad = (this.angle * Math.PI) / 180;
    const x = 320 + Math.cos(rad) * BEAM_RADIUS;
    const y = 320 + Math.sin(rad) * BEAM_RADIUS;

    const activeNodeId = this.findClosestNode(rad);

    const state: ScannerState = { angle: this.angle, x, y, activeNodeId };
    this.listeners.forEach((l) => l(state));
  };

  private findClosestNode(rad: number): string | null {
    const nodes = nodeRegistry.getAll();
    let closest: string | null = null;
    let minDist = Infinity;

    nodes.forEach((node) => {
      if (node.radius === 0) return; // skip Core center

      const nodeRad = (node.angle * Math.PI) / 180;

      // Angular distance (wraps at 2π)
      let diff = Math.abs(rad - nodeRad);
      if (diff > Math.PI) diff = 2 * Math.PI - diff;

      if (diff < 0.28 && diff < minDist) { // ~16 degrees tolerance
        minDist = diff;
        closest = node.id;
      }
    });

    return closest;
  }

  getAngle() {
    return this.angle;
  }

  subscribe(callback: (state: ScannerState) => void) {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  }
}

const scannerEngine = new ScannerEngine();

export default scannerEngine;
