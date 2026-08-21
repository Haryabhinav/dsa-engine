import type { Health, Hint, NextUp, Progress, StageEvent } from "./types";

/**
 * One place that talks to the gateway.
 *
 * The 428 case is modelled explicitly rather than thrown away: the predict-first
 * gate is enforced server-side precisely so the client cannot skip it, and a UI
 * that treated it as a generic failure would be hiding a deliberate design
 * decision behind an error toast.
 */

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try {
      const body = (await r.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* non-JSON error body; the status is all we have */
    }
    throw new ApiError(detail, r.status);
  }
  return (await r.json()) as T;
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export const api = {
  health: () => fetch("/healthz").then(json<Health>),

  problems: () => fetch("/api/problems").then(json<string[]>),

  next: (student: string) =>
    fetch(`/api/next?student=${encodeURIComponent(student)}`).then(json<NextUp>),

  progress: (student: string) =>
    fetch(`/api/progress?student=${encodeURIComponent(student)}`).then(json<Progress>),

  diagnose: (problem: string, code: string, student: string | null) =>
    fetch("/api/diagnose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ problem: `problems/${problem}`, code, ext: ".py", student }),
    }).then(json<{ run: string; queued: number }>),

  hint: (run: string, tier: number, guess: string) =>
    fetch("/api/hint", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run, tier, guess }),
    }).then(json<Hint>),
};

/**
 * Subscribe to a cascade. Returns an unsubscribe function.
 *
 * The `done` sentinel closes the stream from the client side; without it the
 * EventSource reconnects forever and re-runs nothing, which looks like a hang.
 */
export function streamCascade(
  run: string,
  onEvent: (e: StageEvent) => void,
  onClose?: () => void,
): () => void {
  const es = new EventSource(`/api/stream?run=${encodeURIComponent(run)}`);
  es.onmessage = (m) => {
    const ev = JSON.parse(m.data) as StageEvent;
    if (ev.stage === "done") {
      es.close();
      onClose?.();
      return;
    }
    onEvent(ev);
  };
  es.onerror = () => {
    es.close();
    onClose?.();
  };
  return () => es.close();
}
