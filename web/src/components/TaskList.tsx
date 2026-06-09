import type { TaskView } from "../types";

const ICON: Record<string, string> = {
  pending: "○",
  running: "◐",
  completed: "●",
  failed: "✕",
  skipped: "⊘",
};

export function TaskList({ tasks }: { tasks: TaskView[] }) {
  return (
    <section className="panel">
      <h2>Tasks</h2>
      <ul className="tasks">
        {tasks.length === 0 && <li className="muted">no tasks yet — run a workflow</li>}
        {tasks.map((t) => (
          <li key={t.id} className={`task ${t.status}`}>
            <span className="task-icon">{ICON[t.status]}</span>
            <span className="task-id">{t.id}</span>
            {t.device && <span className="task-device">{t.device}</span>}
            <span className="task-note">{t.note}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
