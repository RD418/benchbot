import type { WorkflowRunSummary } from "../types";

interface Props {
  runs: WorkflowRunSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function RunList({ runs, selectedId, onSelect }: Props) {
  return (
    <section className="panel">
      <h2>Runs</h2>
      <ul className="runs">
        {runs.length === 0 && <li className="muted">no runs yet — trigger one</li>}
        {runs.map((r) => (
          <li key={r.id}>
            <button
              className={`run-item ${r.id === selectedId ? "selected" : ""}`}
              onClick={() => onSelect(r.id)}
            >
              <span className={`badge ${r.status}`}>{r.status}</span>
              <span className="run-name">{r.name}</span>
              <span className="run-id">{r.id.slice(0, 8)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
