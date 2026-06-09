import type {
  StoredWorkflowRun,
  WorkflowEvent,
  WorkflowRunSummary,
} from "./types";

// Base URL of the BenchBot API. Defaults to the local dev server; override at
// build/dev time with VITE_API_URL.
export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return (await res.json()) as T;
}

export function listWorkflows(): Promise<WorkflowRunSummary[]> {
  return getJSON("/workflows");
}

export function getWorkflow(id: string): Promise<StoredWorkflowRun> {
  return getJSON(`/workflows/${id}`);
}

export function getWorkflowEvents(id: string): Promise<WorkflowEvent[]> {
  return getJSON(`/workflows/${id}/events`);
}

export interface DemoOptions {
  seed: number;
  hardRate: number;
  halt: boolean;
}

export async function runDemo(opts: DemoOptions): Promise<{ id: string }> {
  const params = new URLSearchParams({
    seed: String(opts.seed),
    hard_rate: String(opts.hardRate),
    halt: String(opts.halt),
  });
  const res = await fetch(`${API_URL}/workflows/demo?${params.toString()}`, { method: "POST" });
  if (!res.ok) throw new Error(`run demo failed: ${res.status}`);
  return (await res.json()) as { id: string };
}

export interface RunOptions {
  seed: number;
  hardRate: number;
  halt: boolean;
  delay: number;
}
