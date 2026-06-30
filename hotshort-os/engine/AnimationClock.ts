type Subscriber = (time: number, delta: number) => void;

class AnimationClock {
  private subscribers = new Set<Subscriber>();

  private running = false;

  private lastTime = 0;

  private frame = 0;

  start() {
    if (this.running) return;

    this.running = true;

    this.lastTime = performance.now();

    requestAnimationFrame(this.loop);
  }

  stop() {
    this.running = false;
  }

  subscribe(callback: Subscriber) {
    this.subscribers.add(callback);

    return () => {
      this.subscribers.delete(callback);
    };
  }

  getTime() {
    return this.lastTime;
  }

  getFrame() {
    return this.frame;
  }

  private loop = (time: number) => {
    if (!this.running) return;

    const delta = time - this.lastTime;

    this.lastTime = time;

    this.frame++;

    this.subscribers.forEach((callback) => {
      callback(time, delta);
    });

    requestAnimationFrame(this.loop);
  };
}

const animationClock = new AnimationClock();

animationClock.start();

export default animationClock;