import packetEngine from "./PacketEngine";
import pathFinder from "./PathFinder";

interface ScheduleOptions {
  color?: string;
  delay?: number;
}

class PacketScheduler {
  private timers = new Set<number>();

  send(
    from: string,
    to: string,
    options: ScheduleOptions = {}
  ) {
    const path = pathFinder.find(from, to);

    if (path.length < 2) return;

    const {
      color = "#FFE08A",
      delay = 250,
    } = options;

    for (let i = 0; i < path.length - 1; i++) {
      const timer = window.setTimeout(() => {
        packetEngine.spawn({
          from: path[i],
          to: path[i + 1],
          color,
        });

        this.timers.delete(timer);
      }, i * delay);

      this.timers.add(timer);
    }
  }

  broadcast(
    from: string,
    targets: string[],
    color = "#FFE08A"
  ) {
    targets.forEach((target, index) => {
      const timer = window.setTimeout(() => {
        this.send(from, target, {
          color,
          delay: 180,
        });

        this.timers.delete(timer);
      }, index * 120);

      this.timers.add(timer);
    });
  }

  sequence(
    nodes: string[],
    color = "#FFE08A",
    delay = 250
  ) {
    if (nodes.length < 2) return;

    for (let i = 0; i < nodes.length - 1; i++) {
      const timer = window.setTimeout(() => {
        packetEngine.spawn({
          from: nodes[i],
          to: nodes[i + 1],
          color,
        });

        this.timers.delete(timer);
      }, i * delay);

      this.timers.add(timer);
    }
  }

  clear() {
    this.timers.forEach((timer) =>
      window.clearTimeout(timer)
    );

    this.timers.clear();

    packetEngine.clear();
  }
}

const packetScheduler = new PacketScheduler();

export default packetScheduler;