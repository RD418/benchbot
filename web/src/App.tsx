import { useCallback, useEffect, useState } from "react";
import { getWorkflow, getWorkflowEvents, listWorkflows, runDemo, type RunOptions } from "./api";
import { Controls } from "./components/Controls";
import { DagView } from "./components/DagView";
import { DevicePanel } from "./components/DevicePanel";
import { EventTimeline } from "./components/EventTimeline";
import { RunList } from "./components/RunList";
import { initialDevices, reconcileDevices, reduceDevices } from "./state";
import type {
  StoredWorkflowRun,
  TaskOutcome,
  WorkflowEvent,
  WorkflowRunSummary,
} from "./types";

export default function App() {
  const [runs, setRuns] = useState<WorkflowRunSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [run, setRun] = useState<StoredWorkflowRun | null>(null);
  const [events, setEvents] = useState<WorkflowEvent[]>([]);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setRuns(await listWorkflows());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const select = useCallback(async (id: string) => {
    setSelectedId(id);
    const [stored, stream] = await Promise.all([getWorkflow(id), getWorkflowEvents(id)]);
    setRun(stored);
    setEvents(stream);
  }, []);

  const trigger = useCallback(
    async (opts: RunOptions) => {
      setBusy(true);
      try {
        const { id } = await runDemo({ seed: opts.seed, hardRate: opts.hardRate, halt: opts.halt });
        await refresh();
        await select(id);
      } finally {
        setBusy(false);
      }
    },
    [refresh, select],
  );

  // Derive the DAG node colors and device health from the selected run.
  const outcomes: Record<string, TaskOutcome | undefined> = {};
  if (run) for (const t of run.tasks) outcomes[t.id] = t.outcome;

  let devices = initialDevices();
  for (const ev of events) devices = reduceDevices(devices, ev);
  if (run) devices = reconcileDevices(devices, run.device_health);

  return (
    <div className="app">
      <header className="app-header">
        <h1>BenchBot</h1>
        <span className="subtitle">work-cell observability</span>
        {run && <span className={`status-pill ${run.status}`}>{run.status}</span>}
      </header>

      <Controls running={busy} onRun={trigger} />

      <div className="grid">
        <RunList runs={runs} selectedId={selectedId} onSelect={(id) => void select(id)} />
        <DevicePanel devices={Object.values(devices)} />
      </div>

      {run && (
        <section className="panel">
          <h2>Workflow graph — {run.name}</h2>
          <DagView tasks={run.workflow.tasks} outcomes={outcomes} />
        </section>
      )}

      <EventTimeline events={events} />
    </div>
  );
}
