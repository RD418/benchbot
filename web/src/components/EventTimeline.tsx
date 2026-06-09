import { useEffect, useRef } from "react";
import type { WorkflowEvent } from "../types";

function describe(ev: WorkflowEvent): string {
  switch (ev.type) {
    case "workflow_started":
      return `workflow '${ev.workflow_name}' (${ev.total_tasks} tasks)`;
    case "task_started":
      return `${ev.task_id} → ${ev.device}: ${ev.action}`;
    case "task_retry":
      return `${ev.task_id} retry #${ev.attempt} (${ev.code})`;
    case "task_completed":
      return `${ev.task_id} ✓ ${ev.detail}`;
    case "task_failed":
      return `${ev.task_id} ✕ ${ev.code} on ${ev.device}`;
    case "task_skipped":
      return `${ev.task_id} skipped — ${ev.reason}`;
    case "device_quarantined":
      return `${ev.device} quarantined (${ev.code})`;
    case "workflow_finished":
      return `workflow ${ev.status}`;
  }
}

export function EventTimeline({ events }: { events: WorkflowEvent[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  return (
    <section className="panel timeline">
      <h2>Event stream</h2>
      <div className="events">
        {events.map((ev) => (
          <div key={ev.seq} className={`event ev-${ev.type}`}>
            <span className="seq">{String(ev.seq).padStart(2, "0")}</span>
            <span className="ev-type">{ev.type}</span>
            <span className="ev-msg">{describe(ev)}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </section>
  );
}
