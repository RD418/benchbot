// Base URL of the BenchBot API. Defaults to the local dev server; override at
// build/dev time with VITE_API_URL.
export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface RunOptions {
  seed: number;
  hardRate: number;
  halt: boolean;
  delay: number;
}

export function streamUrl(opts: RunOptions): string {
  const params = new URLSearchParams({
    seed: String(opts.seed),
    hard_rate: String(opts.hardRate),
    halt: String(opts.halt),
    delay: String(opts.delay),
  });
  return `${API_URL}/stream/demo?${params.toString()}`;
}
