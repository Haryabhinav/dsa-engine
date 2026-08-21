import { useState } from "react";
import { ApiError, api } from "./api";
import type { Hint, NextUp, Progress } from "./types";

const RUNGS: { tier: number; what: string; why: string }[] = [
  { tier: 0, what: "Name the concept", why: "which idea this problem is really testing" },
  { tier: 1, what: "Point me at it", why: "roughly where to look" },
  { tier: 2, what: "Show the failing case", why: "the smallest input that breaks it" },
  { tier: 3, what: "What kind of mistake", why: "the category of error, still not the fix" },
];

/** The scheduler's recommendation, and why. The reason is the product: "practise
 *  this" is an instruction, "array indexing decayed to 0.05 and 10 topics build on
 *  it" is an argument the student can push back on. */
export function UpNext({ next, onStart }: { next: NextUp | null; onStart: (slug: string) => void }) {
  if (!next) return <div className="muted">Enter a handle to get a recommendation.</div>;
  if (!next.problem) return <div className="muted">{next.reason}</div>;
  const p = next.problem;
  return (
    <>
      <div className="strong">
        {p.title} <span className="muted">· required Θ({p.required})</span>
      </div>
      <div className="muted spaced">{next.reason}</div>
      <button className="primary" onClick={() => onStart(p.slug)}>
        Work on this
      </button>
      {next.due.length > 0 && (
        <table>
          <tbody>
            {next.due.map((d) => (
              <tr key={d.concept}>
                <td>{d.name}</td>
                <td>{d.retention.toFixed(2)}</td>
                <td>{d.lifts_n ? `${d.lifts_n} build on it` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

/** Half-life leads, not retention. Retrievability right after any attempt is ~1.0
 *  by construction, so showing only that displayed five consecutive failures as
 *  mastery (BUILD_LOG F49). */
export function Retention({ progress }: { progress: Progress | null }) {
  if (!progress || progress.concepts.length === 0)
    return <div className="muted">No attempts recorded yet.</div>;
  return (
    <>
      <div className="muted">
        {progress.attempts} attempt{progress.attempts === 1 ? "" : "s"} · {progress.passed} solved ·{" "}
        {progress.failed} failed
      </div>
      <table>
        <tbody>
          <tr className="muted">
            <td>topic</td>
            <td>half-life</td>
            <td>recall now</td>
          </tr>
          {progress.concepts.map((c) => (
            <tr key={c.concept}>
              <td>{c.name}</td>
              <td className={c.half_life_days <= 1.5 ? "bad" : undefined}>
                {c.half_life_days} d
              </td>
              <td>{c.effective.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function HintLadder({ run }: { run: string | null }) {
  const [hints, setHints] = useState<Record<number, Hint>>({});
  const [gate, setGate] = useState<number | null>(null);
  const [guess, setGuess] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function unlock(tier: number, prediction: string) {
    if (!run) return;
    try {
      setErr(null);
      const h = await api.hint(run, tier, prediction);
      setHints((prev) => ({ ...prev, [tier]: h }));
    } catch (e) {
      // 428 is not a malfunction: the predict-first gate is enforced server-side
      // so it cannot be skipped from here. Say what it means.
      setErr(
        e instanceof ApiError && e.status === 428
          ? "Say what you think is wrong first — that is the point of the ladder."
          : String(e instanceof Error ? e.message : e),
      );
    }
  }

  return (
    <>
      <div className="ladder">
        {RUNGS.map(({ tier, what, why }) => {
          const h = hints[tier];
          return (
            <div className={`rung${h ? " open" : ""}`} key={tier}>
              <div className="n">{h ? "●" : "🔒"} {tier}</div>
              <div className="what">
                {h ? (
                  <>
                    {h.text}{" "}
                    <span className="muted">
                      [{h.source.startsWith("gemini") ? h.source : "deterministic stub"}]
                    </span>
                    {h.fell_back && <span className="warn"> (firewall fell back)</span>}
                  </>
                ) : (
                  <>
                    {what}
                    <div className="muted">{why}</div>
                  </>
                )}
              </div>
              {!h && (
                <button
                  disabled={!run}
                  onClick={() => (tier === 0 ? unlock(0, "") : (setGuess(""), setGate(tier)))}
                >
                  Unlock
                </button>
              )}
            </div>
          );
        })}
      </div>
      {err && <div className="warn spaced">{err}</div>}

      {gate !== null && (
        <div className="backdrop" onClick={() => setGate(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="strong">Before I show you —</div>
            <div className="muted">what do you think is wrong?</div>
            <input
              autoFocus
              value={guess}
              placeholder="e.g. my loop bound is off by one"
              onChange={(e) => setGuess(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && guess.trim()) {
                  unlock(gate, guess.trim());
                  setGate(null);
                }
              }}
            />
            <div className="row-end">
              <button onClick={() => setGate(null)}>Cancel</button>
              <button
                className="primary"
                disabled={!guess.trim()}
                onClick={() => {
                  unlock(gate, guess.trim());
                  setGate(null);
                }}
              >
                Unlock
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
