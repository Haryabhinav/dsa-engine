import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamCascade } from "./api";
import { Cascade } from "./Cascade";
import { HintLadder, Retention, UpNext } from "./Panels";
import type { Health, NextUp, Progress, StageEvent, StageId, StageState } from "./types";

const PLACEHOLDER = [
  "Write your solution here.",
  "",
  "Read all input from stdin, print only the answer.",
  "Most problems: a first line 'n k', then n integers.",
  "count-inversions: 'n', then n integers (no k).",
  "longest-unique-substring: 'n', then a string.",
].join("\n");

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [problem, setProblem] = useState("");
  const [student, setStudent] = useState(() => localStorage.getItem("dsa_student") ?? "");
  const [code, setCode] = useState("");
  const [stages, setStages] = useState<Partial<Record<StageId, StageState>>>({});
  const [run, setRun] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [next, setNext] = useState<NextUp | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);
  const stop = useRef<(() => void) | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api.problems().then((p) => {
      setProblems(p);
      setProblem((cur) => cur || p[0] || "");
    });
  }, []);

  const refreshTutor = useCallback(async (who: string) => {
    if (!who.trim()) {
      setNext(null);
      setProgress(null);
      return;
    }
    try {
      setNext(await api.next(who));
      setProgress(await api.progress(who));
    } catch {
      setNext(null);
    }
  }, []);

  useEffect(() => {
    if (student) void refreshTutor(student);
  }, [student, refreshTutor]);

  async function diagnose() {
    if (!problem || !code.trim() || busy) return;
    stop.current?.();
    setStages({});
    setNote(null);
    setOutcome(null);
    setBusy(true);
    try {
      const { run: id } = await api.diagnose(problem, code, student.trim() || null);
      setRun(id);
      stop.current = streamCascade(
        id,
        (ev: StageEvent) => {
          // The return edge landed: the attempt is now part of the student's
          // mastery state, so refresh the panels that depend on it. Showing this
          // is the difference between a loop and a claim about a loop.
          if (ev.stage === "recorded") {
            setOutcome(
              (ev.solved ? "Solved. " : "Attempt recorded. ") +
                (ev.blamed
                  ? `Decayed ${ev.blamed} on proven-fault evidence.`
                  : `Recorded against ${ev.recorded?.length ?? 0} topic(s).`),
            );
            void refreshTutor(student);
            return;
          }
          if (ev.stage === "error") {
            setNote(ev.detail ?? "failed");
            return;
          }
          const id2 = ev.stage as StageId;
          setStages((prev) => ({
            ...prev,
            [id2]: {
              status: ev.status,
              // Preserve the tri-state. `ok` absent means "no verdict", which is
              // not the same as false, and flattening it painted STRUCTURAL green.
              ok: ev.status === "done" ? ev.ok : prev[id2]?.ok,
              event: ev.status === "done" ? ev : prev[id2]?.event,
            },
          }));
          if (ev.status === "running")
            setStages((prev) => ({
              ...prev,
              [id2]: { status: "running", ok: undefined, event: ev.detail ? ev : undefined },
            }));
        },
        () => setBusy(false),
      );
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <>
      <header>
        <h1>DSA Diagnosis Engine</h1>
        <span className="sub">deterministic first · the model never sees the fix</span>
        <span className="spacer" />
        {health && (
          <span className="sub" title="isolation and hint source">
            {health.sandbox ? "isolated" : "host execution"} ·{" "}
            {health.llm ? "live hints" : "stub hints"}
          </span>
        )}
        <input
          value={student}
          placeholder="your handle"
          title="Identity, not authentication. Mastery state is kept per handle."
          onChange={(e) => setStudent(e.target.value)}
          onBlur={() => localStorage.setItem("dsa_student", student.trim())}
        />
        <select value={problem} onChange={(e) => setProblem(e.target.value)}>
          {problems.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <button className="primary" onClick={diagnose} disabled={busy || !code.trim()}>
          {busy ? "Diagnosing…" : "Diagnose"}
        </button>
      </header>

      <main>
        <section className="col">
          <div className="card">
            <h2>Up next</h2>
            <UpNext
              next={next}
              onStart={(slug) => {
                setProblem(slug);
                setCode("");
                setStages({});
              }}
            />
          </div>
          <div className="card">
            <h2>Submission</h2>
            <textarea
              spellCheck={false}
              value={code}
              placeholder={PLACEHOLDER}
              onChange={(e) => setCode(e.target.value)}
            />
            {outcome && <div className="note">{outcome}</div>}
            {note && <div className="note warn">{note}</div>}
          </div>
        </section>

        <section className="col">
          <div className="card">
            <h2>What we checked</h2>
            <Cascade state={stages} />
          </div>
          <div className="card">
            <h2>Hint ladder</h2>
            <HintLadder run={run} />
            <div className="note">
              Each rung unlocks deliberately, and unlocking asks what you think is wrong
              first. Locked content is never sent to this page — it is fetched only when
              you unlock it.
            </div>
          </div>
          <div className="card">
            <h2>Your retention</h2>
            <Retention progress={progress} />
            <div className="note">
              <b>half-life</b> is how long a memory lasts before it needs refreshing —
              solving multiplies it, failing halves it, so it moves the moment you
              attempt something. <b>recall now</b> couples retention through
              prerequisites. Right after any attempt recall-now is near 1.00 by
              construction, which is why half-life is the column to watch.
            </div>
          </div>
        </section>
      </main>
    </>
  );
}
