import animationClock from "./AnimationClock";
import eventBus from "./EventBus";

export interface ReactorState {
  energy: number;
  temperature: number;
  pulse: number;
  thinking: boolean;
  rotation: number;
}

class ReactorEngine {
  private state: ReactorState = {
    energy: 0.4,
    temperature: 0.3,
    pulse: 0,
    thinking: false,
    rotation: 0,
  };

  private listeners = new Set<
    (state: ReactorState) => void
  >();

  constructor() {
    animationClock.subscribe(this.update);
  }

  private update = (_time: number, delta: number) => {
    const dt = delta / 1000;

    // Smooth pulse decay
    this.state.pulse += (0 - this.state.pulse) * dt * 2.8;

    // Rotation
    this.state.rotation +=
      (this.state.thinking ? 14 : 4) * dt;

    // Notify UI
    this.listeners.forEach((listener) =>
      listener({ ...this.state })
    );
  };

  subscribe(
    callback: (state: ReactorState) => void
  ) {
    this.listeners.add(callback);

    callback({ ...this.state });

    return () => this.listeners.delete(callback);
  }

  setThinking(value: boolean) {
    this.state.thinking = value;

    eventBus.emit(
      value ? "NODE_ACTIVE" : "NODE_IDLE"
    );
  }

  setEnergy(value: number) {
    this.state.energy = Math.max(
      0,
      Math.min(1, value)
    );
  }

  setTemperature(value: number) {
    this.state.temperature = Math.max(
      0,
      Math.min(1, value)
    );
  }

  pulse(strength = 1) {
    this.state.pulse = strength;

    eventBus.emit("CORE_PULSE", {
      strength,
    });
  }

  getState() {
    return { ...this.state };
  }
}

const reactorEngine = new ReactorEngine();

export default reactorEngine;