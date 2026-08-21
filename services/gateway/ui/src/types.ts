/**
 * Wire types for the cascade stream and the tutor endpoints.
 *
 * These exist because of BUILD_LOG F40. The vanilla UI read `d.sites`, `d.tried`,
 * `d.k` and `d.judge` straight off a parsed SSE payload with no idea what shape
 * it was, and shipped four bugs in one run: `undefined mutation sites`, a
 * fabricated `k = 0 ± 0`, a crash rendered as a wrong answer, and a green tick on
 * "no verdict". Every one was a field either absent or misinterpreted.
 *
 * Optionality here is not decoration. `judge?` and `band: string | null` say out
 * loud that the speed stage may decline to claim anything, which is exactly the
 * distinction the old code flattened.
 */

export type StageId = "S0" | "S1" | "S2" | "S3" | "S4";
export type Status = "running" | "done" | "failed";
export type Tier = "PROVEN" | "LOCALIZED" | "STRUCTURAL";

/** A crash is NOT a wrong answer; the engine distinguishes them and so must we. */
export type FailureKind = "wrong_answer" | "runtime_error";

export interface JudgeResult {
  n: number;
  limit_ms: number;
  ms: number | null; // null when it never finished
  timed_out: boolean;
  ok: boolean;
}

export interface StageEvent {
  stage: StageId | "done" | "error" | "recorded";
  status: Status;
  /** Present on most stages; on `running` it describes what is happening. */
  detail?: string;
  /** Explicit tri-state: true = pass, false = fail, undefined = no verdict. */
  ok?: boolean;
  skipped?: boolean;

  // S0
  isolated?: boolean;

  // S2
  kind?: FailureKind;
  chain?: string;
  input?: string;
  expected?: string;
  actual?: string;

  // S3
  tier?: Tier;
  line?: number | null;
  sites?: number;
  tried?: number;
  band?: number[];

  // S4
  judge?: JudgeResult;
  /** Coarse growth class, or null when the data cannot support one. */
  growth?: string | null;
  required?: string;
  k?: number;
  ci?: number;
  noise?: number;
  points?: [number, number][];

  // recorded (the tutor return edge)
  solved?: boolean;
  recorded?: string[];
  blamed?: string | null;
  suspects?: string[];
  error?: string;

  // error
  ours?: boolean;
}

export interface StageState {
  status: Status | "pending";
  ok?: boolean;
  event?: StageEvent;
}

export interface ProblemRef {
  slug: string;
  title: string;
  statement: string;
  required: string;
  concepts: string[];
}

export interface DueConcept {
  concept: string;
  name: string;
  retention: number;
  lift: number;
  lifts_n: number;
}

export interface NextUp {
  student: string;
  new: boolean;
  due: DueConcept[];
  problem: ProblemRef | null;
  reason: string;
  match?: string[];
}

export interface ConceptProgress {
  concept: string;
  name: string;
  own: number;
  effective: number;
  half_life_days: number;
}

export interface Progress {
  student: string;
  concepts: ConceptProgress[];
  attempts: number;
  passed: number;
  failed: number;
}

export interface Hint {
  tier: number;
  text: string;
  fell_back: boolean;
  source: string;
  rejections: string[];
}

export interface Health {
  ok: boolean;
  sandbox: boolean;
  llm: boolean;
  runs: number;
  inflight: number;
}
