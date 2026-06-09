// Pure layered DAG layout (longest-path layering). Places each task in a column
// equal to its longest dependency depth, stacks tasks within a column, and emits
// edges from depends_on. Small, deterministic, dependency-free — the graph is
// tiny, so a hand-rolled layout beats pulling in a graph library.

import type { WorkflowDefTask } from "./types";

export const NODE_W = 140;
export const NODE_H = 56;
const COL_W = 200;
const ROW_H = 92;
const PAD = 24;

export interface DagNode {
  id: string;
  device: string;
  level: number;
  x: number;
  y: number;
}

export interface DagEdge {
  from: string;
  to: string;
}

export interface DagLayout {
  nodes: DagNode[];
  edges: DagEdge[];
  width: number;
  height: number;
}

export function layoutDag(tasks: WorkflowDefTask[]): DagLayout {
  const byId = new Map(tasks.map((t) => [t.id, t]));
  const level = new Map<string, number>();

  const levelOf = (id: string): number => {
    const cached = level.get(id);
    if (cached !== undefined) return cached;
    const task = byId.get(id);
    const deps = task ? task.depends_on.filter((d) => byId.has(d)) : [];
    const value = deps.length === 0 ? 0 : Math.max(...deps.map((d) => levelOf(d) + 1));
    level.set(id, value);
    return value;
  };
  for (const task of tasks) levelOf(task.id);

  const rowByLevel = new Map<number, number>();
  const nodes: DagNode[] = tasks.map((task) => {
    const lvl = level.get(task.id) ?? 0;
    const row = rowByLevel.get(lvl) ?? 0;
    rowByLevel.set(lvl, row + 1);
    return { id: task.id, device: task.device, level: lvl, x: PAD + lvl * COL_W, y: PAD + row * ROW_H };
  });

  const edges: DagEdge[] = [];
  for (const task of tasks) {
    for (const dep of task.depends_on) {
      if (byId.has(dep)) edges.push({ from: dep, to: task.id });
    }
  }

  const maxLevel = Math.max(0, ...nodes.map((n) => n.level));
  const maxRows = Math.max(1, ...rowByLevel.values());
  return {
    nodes,
    edges,
    width: PAD * 2 + maxLevel * COL_W + NODE_W,
    height: PAD * 2 + (maxRows - 1) * ROW_H + NODE_H,
  };
}
