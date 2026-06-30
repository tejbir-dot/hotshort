import animationClock from "./AnimationClock";

export interface CameraState {
  x: number;       // drift offset px
  y: number;
  scale: number;   // 1 ± 0.012
}

class CameraEngine {
  private t = 0;
  private listeners = new Set<(state: CameraState) => void>();

  // Independent oscillator frequencies (irrational ratios = never repeats)
  private readonly DRIFT_X_FREQ  = 0.071;
  private readonly DRIFT_Y_FREQ  = 0.053;
  private readonly BREATHE_FREQ  = 0.038;
  private readonly DRIFT_AMP     = 3.5;   // px
  private readonly BREATHE_AMP   = 0.012; // scale units

  constructor() {
    animationClock.subscribe(this.update);
  }

  private update = (_: number, delta: number) => {
    this.t += Math.min(delta / 1000, 0.05);

    const x = Math.sin(this.t * this.DRIFT_X_FREQ * Math.PI * 2) * this.DRIFT_AMP;
    const y = Math.cos(this.t * this.DRIFT_Y_FREQ * Math.PI * 2) * this.DRIFT_AMP;
    const scale = 1 + Math.sin(this.t * this.BREATHE_FREQ * Math.PI * 2) * this.BREATHE_AMP;

    const state: CameraState = { x, y, scale };
    this.listeners.forEach((l) => l(state));
  };

  getState(): CameraState {
    return {
      x: 0,
      y: 0,
      scale: 1,
    };
  }

  subscribe(callback: (state: CameraState) => void) {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  }
}

const cameraEngine = new CameraEngine();

export default cameraEngine;
