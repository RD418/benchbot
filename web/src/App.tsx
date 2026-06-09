import { useCallback, useEffect, useRef, useState } from "react";
import { streamUrl, type RunOptions } from "./api";
import { Controls } from "./components/Controls";
import { DevicePanel } from "./components/DevicePanel";
import { EventTimeline } from "./components/EventTimeline";
import { TaskList } from "./components/TaskList";
import {
  initialDevices,
  reconcileDevices,
  reduceDevices,
  reduceTasks,
  tasksFromResult,
} from "./state";
import type { DeviceView, StreamMessage, TaskView, WorkflowEvent } from "./types";

export default function App() {
  const [events, setEvents] = useState<WorkflowEvent[]>([]);
  const [devices, setDevices] = useState<Record<string, DeviceView>>(initialDevices);
  const [tasks, setTasks] = useState<Record<string, TaskView>>({});
  const [status, setStatus] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const run = useCallback((opts: RunOptions) => {
    esRef.current?.close();
    setEvents([]);
    setDevices(initialDevices());
    setTasks({});
    setStatus(null);
    setRunning(true);

    const es = new EventSource(streamUrl(opts));
    esRef.current = es;

    es.onmessage = (e: MessageEvent<string>) => {
      const msg: StreamMessage = JSON.parse(e.data);
      if (msg.kind === "event") {
        const ev = msg.event;
        setEvents((prev) => [...prev, ev]);
        setDevices((prev) => reduceDevices(prev, ev));
        setTasks((prev) => reduceTasks(prev, ev));
      } else {
        // Authoritative final state.
        setStatus(msg.result.status);
        setDevices((prev) => reconcileDevices(prev, msg.result.device_health));
        setTasks(tasksFromResult(msg.result.tasks));
        es.close();
        setRunning(false);
      }
    };
    es.onerror = () => {
      es.close();
      setRunning(false);
    };
  }, []);

  useEffect(() => () => esRef.current?.close(), []);

  return (
    <div className="app">
      <header className="app-header">
        <h1>BenchBot</h1>
        <span className="subtitle">work-cell observability</span>
        {status && <span className={`status-pill ${status}`}>{status}</span>}
      </header>

      <Controls running={running} onRun={run} />

      <div className="grid">
        <DevicePanel devices={Object.values(devices)} />
        <TaskList tasks={Object.values(tasks)} />
      </div>

      <EventTimeline events={events} />
    </div>
  );
}
