import nodeRegistry from "./NodeRegistry";

class PathFinder {
  find(
    start: string,
    target: string
  ): string[] {
    if (start === target) {
      return [start];
    }

    const visited = new Set<string>();

    const queue: {
      node: string;
      path: string[];
    }[] = [
      {
        node: start,
        path: [start],
      },
    ];

    while (queue.length > 0) {
      const current = queue.shift()!;

      if (visited.has(current.node)) {
        continue;
      }

      visited.add(current.node);

      const node = nodeRegistry.get(current.node);

      if (!node) continue;

      for (const next of node.connections) {
        const path = [
          ...current.path,
          next,
        ];

        if (next === target) {
          return path;
        }

        queue.push({
          node: next,
          path,
        });
      }
    }

    return [];
  }

  next(
    current: string
  ): string | null {
    const node = nodeRegistry.get(current);

    if (!node) return null;

    return node.connections[0] ?? null;
  }

  previous(
    target: string
  ): string | null {
    const nodes = nodeRegistry.getAll();

    const parent = nodes.find((node) =>
      node.connections.includes(target)
    );

    return parent?.id ?? null;
  }

  fullPipeline() {
    return this.find(
      "Core",
      "Renderer"
    );
  }

  exists(
    from: string,
    to: string
  ) {
    return this.find(from, to).length > 0;
  }
}

const pathFinder = new PathFinder();

export default pathFinder;