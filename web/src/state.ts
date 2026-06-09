// Pure reducers that derive live device/task views from the event stream — the
// same "reconstruct state from events" idea the backend uses for run status.

import type {
  DeviceView,
  Health,
  TaskState,
  TaskView,
  WorkflowEvent,
} from "./types";

export const DEVICE_NAMES = ["lh1", "reader1", "inc1"] as const;

export function initialDevices(): Record<string, DeviceView> {
  return Object.fromEntries(
    DEVICE_NAMES.map((name) => [name, { name, health: "ok", errors: 0, retries: 0 }]),
  );
}

function derivedHealth(d: DeviceView, addedErrors: number): Health {
  if (d.health === "down") return "down";
  return d.errors + addedErrors > 0 ? "degraded" : "ok";
}

export function reduceDevices(
  prev: Record<string, DeviceView>,
  ev: WorkflowEvent,
): Record<string, DeviceView> {
  const bump = (name: string, dErr: number, dRetry: number): Record<string, DeviceView> => {
    const d = prev[name];
    if (!d) return prev;
    return {
      ...prev,
      [name]: {
        ...d,
        errors: d.errors + dErr,
        retries: d.retries + dRetry,
        health: derivedHealth(d, dErr),
      },
    };
  };

  switch (ev.type) {
    case "task_retry":
      return bump(ev.device, 1, 1);
    case "task_failed":
      return bump(ev.device, 1, 0);
    case "device_quarantined": {
      const d = prev[ev.device];
      if (!d) return prev;
      return { ...prev, [ev.device]: { ...d, health: "down" } };
    }
    default:
      return prev;
  }
}

export function reduceTasks(
  prev: Record<string, TaskView>,
  ev: WorkflowEvent,
): Record<string, TaskView> {
  switch (ev.type) {
    case "task_started":
      return { ...prev, [ev.task_id]: { id: ev.task_id, device: ev.device, status: "running" } };
    case "task_completed":
      return {
        ...prev,
        [ev.task_id]: { ...prev[ev.task_id], id: ev.task_id, status: "completed", note: ev.detail },
      };
    case "task_failed":
      return {
        ...prev,
        [ev.task_id]: {
          ...prev[ev.task_id],
          id: ev.task_id,
          device: ev.device,
          status: "failed",
          note: ev.code,
        },
      };
    case "task_skipped":
      return { ...prev, [ev.task_id]: { id: ev.task_id, status: "skipped", note: ev.reason } };
    default:
      return prev;
  }
}

export function reconcileDevices(
  prev: Record<string, DeviceView>,
  health: Record<string, Health>,
): Record<string, DeviceView> {
  const next = { ...prev };
  for (const [name, h] of Object.entries(health)) {
    if (next[name]) next[name] = { ...next[name], health: h };
  }
  return next;
}

export function tasksFromResult(tasks: TaskState[]): Record<string, TaskView> {
  return Object.fromEntries(
    tasks.map((t) => [
      t.id,
      { id: t.id, device: t.device, status: t.outcome, note: t.detail ?? t.failure?.code ?? "" },
    ]),
  );
}
