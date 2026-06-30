export type NodeStatus =
  | "idle"
  | "thinking"
  | "processing"
  | "success"
  | "warning";

export interface NeuralNode {
  id: string;

  label: string;

  color: string;

  angle: number;

  radius: number;

  energy: number;

  status: NodeStatus;

  connections: string[];
}

class NodeRegistry {
  private nodes = new Map<string, NeuralNode>();

  private listeners = new Set<
    (nodes: NeuralNode[]) => void
  >();

  constructor() {
    this.registerDefaults();
  }

  private registerDefaults() {
    this.register({
      id: "Core",
      label: "Core",
      color: "#FFE08A",
      angle: -90,
      radius: 0,
      energy: 1,
      status: "idle",
      connections: ["Whisper"],
    });

    this.register({
      id: "Whisper",
      label: "Whisper",
      color: "#59B7FF",
      angle: -45,
      radius: 270,
      energy: .3,
      status: "idle",
      connections: ["Semantic"],
    });

    this.register({
      id: "Semantic",
      label: "Semantic",
      color: "#FFFFFF",
      angle: 0,
      radius: 270,
      energy: .3,
      status: "idle",
      connections: ["Hook"],
    });

    this.register({
      id: "Hook",
      label: "Hook Hunter",
      color: "#FFE08A",
      angle: 45,
      radius: 270,
      energy: .3,
      status: "idle",
      connections: ["Ranking"],
    });

    this.register({
      id: "Ranking",
      label: "Ranking",
      color: "#F6C453",
      angle: 90,
      radius: 270,
      energy: .3,
      status: "idle",
      connections: ["Editor"],
    });

    this.register({
      id: "Editor",
      label: "Editor",
      color: "#FFAA52",
      angle: 135,
      radius: 270,
      energy: .3,
      status: "idle",
      connections: ["Caption"],
    });

    this.register({
      id: "Caption",
      label: "Caption",
      color: "#A98CFF",
      angle: 180,
      radius: 270,
      energy: .3,
      status: "idle",
      connections: ["Renderer"],
    });

    this.register({
      id: "Renderer",
      label: "Renderer",
      color: "#6BE6FF",
      angle: 225,
      radius: 270,
      energy: .3,
      status: "idle",
      connections: [],
    });
  }

  register(node: NeuralNode) {
    this.nodes.set(node.id, node);

    this.notify();
  }

  update(
    id: string,
    data: Partial<NeuralNode>
  ) {
    const node = this.nodes.get(id);

    if (!node) return;

    Object.assign(node, data);

    this.notify();
  }

  activate(id: string) {
    this.update(id, {
      status: "processing",
      energy: 1,
    });
  }

  idle(id: string) {
    this.update(id, {
      status: "idle",
      energy: .35,
    });
  }

  success(id: string) {
    this.update(id, {
      status: "success",
      energy: .8,
    });
  }

  get(id: string) {
    return this.nodes.get(id);
  }

  getAll() {
    return [...this.nodes.values()];
  }

  subscribe(
    callback: (nodes: NeuralNode[]) => void
  ) {
    this.listeners.add(callback);

    callback(this.getAll());

    return () =>
      this.listeners.delete(callback);
  }

  private notify() {
    const snapshot = this.getAll();

    this.listeners.forEach((listener) =>
      listener(snapshot)
    );
  }
}

const nodeRegistry = new NodeRegistry();

export default nodeRegistry;
