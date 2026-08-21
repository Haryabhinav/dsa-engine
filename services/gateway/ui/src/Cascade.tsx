import type { JudgeResult, StageEvent, StageId, StageState } from "./types";

/**
 * The cascade rail.
 *
 * Every string here goes through JSX, so it is escaped by React rather than by a
 * hand-written `esc()` I have to remember to call. That is not a stylistic
 * preference: a crashed submission reports its output as `<Traceback ...>`, and
 * the vanilla version fed that to `innerHTML`, where the leading `<` opened a tag
 * and swallowed the message (BUILD_LOG F40). Fifteen `innerHTML` assignments were
 * fifteen chances to forget.
 */

const STAGES: { id: StageId; name: string; question: string }[] = [
  { id: "S0", name: "Problem check", question: "Are the reference solutions trustworthy?" },
  { id: "S1", name: "Sample tests", question: "Do the visible examples pass?" },
  {
    id: "S2",
    name: "Find a failing case",
    question: "Searching random inputs for one where you are wrong, then shrinking it",
  },
  { id: "S3", name: "Locate the fault", question: "Where is the defect, and how certain can we be?" },
  { id: "S4", name: "Speed", question: "Is it fast enough for the required bound?" },
];

/** Three outcomes, never two. A tier is not a pass, and "no verdict" is not success. */
function mark(s: StageState): { glyph: string; cls: string; label: string } {
  if (s.status === "pending") return { glyph: "·", cls: "pend", label: "waiting" };
  if (s.status === "running") return { glyph: "…", cls: "runn", label: "running" };
  if (s.ok === false) return { glyph: "✕", cls: "bad", label: "failed" };
  if (s.ok === true) return { glyph: "✓", cls: "good", label: "passed" };
  return { glyph: "–", cls: "muted", label: "no verdict" };
}

const secs = (ms: number) => `${(ms / 1000).toFixed(2)} s`;

function SpeedVerdict({ j }: { j: JudgeResult }) {
  if (j.timed_out)
    return (
      <>
        <span className="tierbadge bad">TOO SLOW</span> did not finish at n={j.n}{" "}
        <span className="muted">(limit {secs(j.limit_ms)})</span>
      </>
    );
  if (!j.ok)
    return (
      <>
        <span className="tierbadge bad">TOO SLOW</span> {secs(j.ms ?? 0)} at n={j.n}, limit is{" "}
        {secs(j.limit_ms)}
      </>
    );
  return (
    <>
      finishes in {secs(j.ms ?? 0)} at n={j.n}{" "}
      <span className="muted">(limit {secs(j.limit_ms)})</span>
    </>
  );
}

function Headline({ id, ev }: { id: StageId; ev: StageEvent }) {
  if (ev.skipped) return <span className="muted">{ev.detail}</span>;

  if (id === "S2") {
    if (ev.kind === "runtime_error")
      return (
        <>
          <span className="tierbadge bad">CRASHED</span> on this input
        </>
      );
    return <>{ev.chain ? `shrunk ${ev.chain}` : ev.detail}</>;
  }

  if (id === "S3" && ev.tier) {
    const cls = ev.tier === "PROVEN" ? "good" : ev.tier === "LOCALIZED" ? "warn" : "muted";
    return <span className={`tierbadge ${cls}`}>{ev.tier}</span>;
  }

  if (id === "S4" && ev.judge) return <SpeedVerdict j={ev.judge} />;

  return <>{ev.detail}</>;
}

function Body({ id, ev }: { id: StageId; ev: StageEvent }) {
  if (id === "S2" && ev.input) {
    const crashed = ev.kind === "runtime_error";
    // A crash has no output to compare, so "yours / expected" is the wrong frame:
    // it invites hunting for a wrong number the program never produced.
    return (
      <pre className="kv">
        {crashed
          ? `input     ${ev.input}\nyour run  ${(ev.actual ?? "").replace(/^<|>$/g, "")}`
          : `input     ${ev.input}\nyours     ${ev.actual}\nexpected  ${ev.expected}`}
      </pre>
    );
  }

  if (id === "S3" && ev.tier) {
    return (
      <pre className="kv">
        {`${ev.sites ?? 0} mutation sites · ${ev.tried ?? 0} tried after coverage pruning` +
          (ev.tier === "PROVEN" && ev.line ? `\ndefect proven at line ${ev.line}` : "") +
          (ev.tier === "LOCALIZED" && ev.band?.length
            ? `\nlikely within lines ${ev.band.join(", ")}`
            : "")}
      </pre>
    );
  }

  if (id === "S4" && ev.judge) {
    const pts = ev.points ?? [];
    return (
      <>
        <pre className="kv">
          {(ev.growth
            ? `growth looks ${ev.growth}`
            : `growth class could not be determined${
                (ev.noise ?? 0) > 0.25 ? " (machine too busy to time reliably)" : ""
              }`) + `\nrequired: Θ(${ev.required})`}
        </pre>
        {pts.length > 0 && (
          <details>
            <summary className="muted">show measurements</summary>
            <pre className="kv">
              {/* Never print a fit that was not measured: fewer than 3 points has no
                  slope, and the default field printed as "k = 0 ± 0" once (F10/F40). */}
              {(pts.length >= 3 ? `exponent k = ${ev.k} ± ${ev.ci}\n` : "") +
                pts.map(([n, ms]) => `n=${String(n).padEnd(8)}${ms} ms`).join("\n")}
            </pre>
          </details>
        )}
      </>
    );
  }

  return null;
}

export function Cascade({ state }: { state: Partial<Record<StageId, StageState>> }) {
  return (
    <div className="rail">
      {STAGES.map(({ id, name, question }) => {
        const s = state[id] ?? { status: "pending" as const };
        const m = mark(s);
        return (
          <div className="stage" key={id}>
            <div className="tag">{name}</div>
            <div className="st">
              <span className={m.cls} title={m.label}>
                {m.glyph}
              </span>{" "}
              {s.event ? (
                <span className="lbl">
                  <Headline id={id} ev={s.event} />
                </span>
              ) : (
                <span className="muted">{question}</span>
              )}
              {s.event && <Body id={id} ev={s.event} />}
            </div>
          </div>
        );
      })}
      <div className="note legend">
        <span className="pend">·</span> waiting <span className="runn">…</span> running{" "}
        <span className="good">✓</span> passed <span className="bad">✕</span> failed{" "}
        <span className="muted">–</span> no verdict — it declined rather than guess
      </div>
    </div>
  );
}
