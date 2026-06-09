import { NODE_H, NODE_W, layoutDag } from "../dag";
import type { TaskOutcome, WorkflowDefTask } from "../types";

interface Props {
  tasks: WorkflowDefTask[];
  outcomes: Record<string, TaskOutcome | undefined>;
}

// Renders the workflow as a directed graph: nodes colored by outcome, and edges
// downstream of a non-completed task drawn as a "broken" (red, dashed) path —
// so the failure and the skipped branch it caused are visible at a glance.
export function DagView({ tasks, outcomes }: Props) {
  const { nodes, edges, width, height } = layoutDag(tasks);
  const pos = new Map(nodes.map((n) => [n.id, n]));

  return (
    <svg className="dag" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
      {edges.map((e) => {
        const a = pos.get(e.from);
        const b = pos.get(e.to);
        if (!a || !b) return null;
        const x1 = a.x + NODE_W;
        const y1 = a.y + NODE_H / 2;
        const x2 = b.x;
        const y2 = b.y + NODE_H / 2;
        const mx = (x1 + x2) / 2;
        const broken = outcomes[e.from] !== "completed";
        return (
          <path
            key={`${e.from}->${e.to}`}
            d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`}
            className={`edge ${broken ? "edge-broken" : ""}`}
            fill="none"
          />
        );
      })}
      {nodes.map((n) => {
        const outcome = outcomes[n.id] ?? "pending";
        return (
          <g key={n.id} transform={`translate(${n.x},${n.y})`}>
            <rect width={NODE_W} height={NODE_H} rx={8} className={`node node-${outcome}`} />
            <text x={12} y={23} className="node-id">
              {n.id}
            </text>
            <text x={12} y={42} className="node-dev">
              {n.device} · {outcome}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
