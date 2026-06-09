// Mirrors the backend's workflow events and result (benchbot.workcell).

export type WorkflowEvent =
  | { type: "workflow_started"; seq: number; workflow_name: string; total_tasks: number }
  | { type: "task_started"; seq: number; task_id: string; device: string; action: string }
  | {
      type: "task_retry";
      seq: number;
      task_id: string;
      device: string;
      attempt: number;
      code: string;
      message: string;
    }
  | { type: "task_completed"; seq: number; task_id: string; detail: string }
  | { type: "task_failed"; seq: number; task_id: string; device: string; code: string; message: string }
  | { type: "task_skipped"; seq: number; task_id: string; reason: string }
  | { type: "device_quarantined"; seq: number; device: string; code: string; message: string }
  | { type: "workflow_finished"; seq: number; status: string };

export interface TaskState {
  id: string;
  device: string;
  outcome: "completed" | "failed" | "skipped";
  detail?: string | null;
  failure?: { code: string; message: string } | null;
}

export interface WorkflowResult {
  status: "completed" | "degraded" | "halted" | "invalid";
  tasks: TaskState[];
  device_health: Record<string, Health>;
}

export type StreamMessage =
  | { kind: "event"; event: WorkflowEvent }
  | { kind: "done"; result: WorkflowResult };

export type Health = "ok" | "degraded" | "down";
export type TaskStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export interface DeviceView {
  name: string;
  health: Health;
  errors: number;
  retries: number;
}

export interface TaskView {
  id: string;
  device?: string;
  status: TaskStatus;
  note?: string;
}
