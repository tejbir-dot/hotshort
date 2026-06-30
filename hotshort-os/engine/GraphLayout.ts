import nodeRegistry from "./NodeRegistry";

export interface GraphPoint {
  id: string;

  x: number;

  y: number;

  angle: number;

  radius: number;
}

class GraphLayout {
  private readonly centerX = 0;

  private readonly centerY = 0;

  getNode(id: string): GraphPoint | null {
    const node = nodeRegistry.get(id);

    if (!node) return null;

    const rad = (node.angle * Math.PI) / 180;

    return {
      id: node.id,

      angle: node.angle,

      radius: node.radius,

      x:
        this.centerX +
        Math.cos(rad) * node.radius,

      y:
        this.centerY +
        Math.sin(rad) * node.radius,
    };
  }

  getAll() {
    return nodeRegistry
      .getAll()
      .map((node) => this.getNode(node.id)!)
      .filter(Boolean);
  }

  getConnection(
    from: string,
    to: string
  ) {
    const start = this.getNode(from);

    const end = this.getNode(to);

    if (!start || !end) return null;

    return {
      start,
      end,
    };
  }

  getBezier(
    from: string,
    to: string
  ) {
    const connection = this.getConnection(
      from,
      to
    );

    if (!connection) return null;

    const { start, end } = connection;

    const mx = (start.x + end.x) / 2;

    const my = (start.y + end.y) / 2;

    const dx = end.x - start.x;

    const dy = end.y - start.y;

    const length = Math.sqrt(
      dx * dx + dy * dy
    );

    const curve = Math.min(
      length * 0.35,
      120
    );

    return {
      start,

      end,

      c1: {
        x: mx - dy * 0.35,
        y: my + dx * 0.35,
      },

      c2: {
        x: mx + dy * 0.35,
        y: my - dx * 0.35,
      },

      path: `
M ${start.x} ${start.y}
C
${mx - dy * 0.35} ${my + dx * 0.35},
${mx + dy * 0.35} ${my - dx * 0.35},
${end.x} ${end.y}
`,
    };
  }
}

const graphLayout = new GraphLayout();

export default graphLayout;