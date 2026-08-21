"""The tutor loop — what turns a diagnosis tool into a product.

Everything before this was a one-shot analyser: paste code, get a verdict, done.
Nothing remembered you, nothing decided what you should work on, and nothing
learned from how you did. The knowledge layer that does all three has existed and
been validated since session 4 and had **no interface at all** -- the fifth
instance in this project of built, tested, and wired to nothing (BUILD_LOG F47).

The loop this module closes:

    scheduler picks a problem   ->  student attempts it
              ^                            |
              |                            v
    retention updates          <-  outcome recorded against concepts

Without the return edge the scheduler is a static ranking that never changes, and
"spaced repetition" is a claim rather than a behaviour.

IDENTITY, NOT AUTHENTICATION. A student is a handle they type once. There are no
passwords here and there will not be: a real deployment puts SSO in front of this
and passes the subject through. What this does provide is genuine per-student
separation of mastery state, which the single shared knowledge.db did not.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import time
from typing import Optional

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "analysis"))

import knowledge as kn          # noqa: E402

DB = ROOT / "knowledge.db"
HANDLE_RE = re.compile(r"^[A-Za-z0-9_.-]{2,40}$")


def valid_handle(h: str) -> bool:
    return bool(h and HANDLE_RE.match(h))


def _problems() -> list[dict]:
    out = []
    for d in sorted((ROOT / "problems").iterdir()):
        if not d.is_dir() or not (d / "problem.json").exists():
            continue
        m = json.loads((d / "problem.json").read_text(encoding="utf-8"))
        out.append({
            "slug": d.name,
            "title": m.get("title", d.name),
            "statement": m.get("statement", ""),
            "required": m.get("required_complexity", ""),
            "concepts": [c["id"] for c in m.get("concepts", [])],
            "weights": {c["id"]: c.get("centrality", 0.5) for c in m.get("concepts", [])},
        })
    return out


# Below this retention a concept is genuinely worth revisiting. Above it, the
# student knows it and being told to "review" it is noise -- the first version
# happily reported "Comparison operators has decayed to 1.00 retention", which is
# both false and self-evidently nonsense (F47).
DUE_THRESHOLD = 0.70


def _last_problem(con, student: str) -> Optional[str]:
    """The problem most recently attempted, so we do not immediately re-serve it."""
    r = con.execute("SELECT source FROM review_event WHERE student=? "
                    "ORDER BY ts DESC LIMIT 1", (student,)).fetchone()
    src = (r["source"] if r else "") or ""
    return src.split(":", 1)[1] if src.startswith("submission:") else None


def _all_solid_message(con, student: str, now: float) -> str:
    """"Nothing is due" is true but smug on its own.

    Retrievability right after an attempt is ~1.0 for everyone, so a topic that
    just FAILED still reads as not-due today even though its half-life is down to
    a single day. Naming what will decay first turns a dead-end message into a
    forecast the student can plan around (BUILD_LOG F49).
    """
    rows = con.execute(
        "SELECT concept, stability FROM mastery WHERE student=? AND seen=1 "
        "ORDER BY stability ASC LIMIT 1", (student,)).fetchall()
    base = ("Nothing has decayed below the review threshold yet - "
            "everything you have practised is still fresh. ")
    if not rows:
        return base + "Here is something new to extend the graph."
    names = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM concept")}
    weakest, stab = rows[0]["concept"], float(rows[0]["stability"])
    return (base + f"{names.get(weakest, weakest)} is the shortest-lived at about "
            f"{stab:.1f} day{'' if abs(stab - 1) < 0.05 else 's'} - expect it back "
            f"soon. For now, something new to extend the graph.")


def next_up(student: str, now: Optional[float] = None, k: int = 3) -> dict:
    """What this student should do now, and WHY.

    The reason is part of the payload on purpose. "Practise this" is an
    instruction; "your array-indexing retention has decayed to 0.05 and it
    underpins 10 later topics" is a reason a student can argue with -- and being
    arguable is what separates a tutor from a task list.
    """
    now = now or time.time()
    con = kn.connect(DB)
    try:
        queue = kn.review_queue(con, student, now)
        # A concept is DUE only if it has actually decayed and revisiting it would
        # gain something. Ranking by lift alone let fully-remembered concepts head
        # the list, because "lift 0.0" still sorts somewhere.
        due = [{"concept": c.concept, "name": c.name, "retention": round(c.eff, 3),
                "lift": round(c.lift, 3), "lifts_n": c.lifts_n}
               for c in queue
               if c.eff < DUE_THRESHOLD and c.lift > 1e-6][:6]
        last = _last_problem(con, student)
        seen = {r["concept"] for r in
                con.execute("SELECT concept FROM mastery WHERE student=?", (student,))}
        probs = _problems()

        if not due:
            # Nothing has decayed. That is a real state and deserves a real
            # message, not a fabricated "review this" instruction.
            # A brand-new student has no decay to act on. Start at the shallowest
            # problem rather than the highest-lift one, because "highest lift"
            # on an empty profile just means "hardest".
            fresh = [p for p in probs if p["slug"] != _last_problem(con, student)]
            fresh.sort(key=lambda p: len(p["concepts"]))
            pick = fresh[0] if fresh else (probs[0] if probs else None)
            brand_new = not con.execute(
                "SELECT 1 FROM mastery WHERE student=? LIMIT 1", (student,)).fetchall()
            return {"student": student, "new": brand_new, "due": [],
                    "problem": pick,
                    "reason": ("You are new here, so there is nothing to review yet. "
                               "Starting with a short one to find your level."
                               if brand_new else
                               _all_solid_message(con, student, now))
                    if pick else "No problems are available."}

        target = {d["concept"] for d in due[:k]}
        # Score a problem by how much of the due set it exercises, weighted by how
        # central each concept is to that problem. A problem that merely touches a
        # due concept is worth less than one built on it.
        best, best_score = None, 0.0
        for p in probs:
            if p["slug"] == last and len(probs) > 1:
                continue          # never hand back the problem just attempted
            score = sum(p["weights"].get(c, 0.0) * next(
                (d["lift"] for d in due if d["concept"] == c), 0.0)
                for c in p["concepts"] if c in target)
            if score > best_score:
                best, best_score = p, score
        if best is None:
            best = min(probs, key=lambda p: len(p["concepts"])) if probs else None

        top = due[0]
        why = (f"{top['name']} has decayed to {top['retention']:.2f} retention"
               + (f" and {top['lifts_n']} later topic"
                  f"{'' if top['lifts_n'] == 1 else 's'} build on it"
                  if top["lifts_n"] else "")
               + ".")
        return {"student": student, "new": not seen, "due": due,
                "problem": best, "reason": why,
                "match": sorted(set(best["concepts"]) & target) if best else []}
    finally:
        con.close()


def progress(student: str, now: Optional[float] = None) -> dict:
    """Retention per concept the student has actually touched.

    Deliberately does NOT list all 38 concepts. Showing a wall of 0.00 for things
    someone has never met reads as failure rather than as "not yet", and the whole
    point of the coupled model is that unseen concepts are not weak, they are
    absent.
    """
    now = now or time.time()
    con = kn.connect(DB)
    try:
        r = kn.retrievability(con, student, now)
        names = {row["id"]: row["name"] for row in
                 con.execute("SELECT id, name FROM concept")}
        seen = {row["concept"] for row in
                con.execute("SELECT concept FROM mastery WHERE student=? AND seen=1",
                            (student,))}
        # STABILITY, not just retention. In a half-life model retrievability right
        # after ANY review is ~1.0 by construction -- pass or fail -- because no
        # time has elapsed yet. A student who had just failed five times in a row
        # was therefore shown "own 1.00" for every topic, which reads as mastery
        # (BUILD_LOG F49).
        #
        # What failure actually changes is STABILITY: how long the memory lasts.
        # Passing multiplies it by 1.9, failing halves it. Expressed as a
        # half-life in days that is immediately legible -- "solid for ~6 days"
        # versus "gone in a day" -- and it makes a failed attempt visible now
        # instead of only tomorrow.
        stab = {row["concept"]: row["stability"] for row in con.execute(
            "SELECT concept, stability FROM mastery WHERE student=?", (student,))}
        rows = [{"concept": c, "name": names.get(c, c),
                 "own": round(r.own.get(c, 0.0), 3),
                 "effective": round(r.eff.get(c, 0.0), 3),
                 "half_life_days": round(stab.get(c, 3.0), 1)}
                for c in sorted(seen, key=lambda c: stab.get(c, 3.0))]
        events = con.execute(
            "SELECT outcome, COUNT(*) n FROM review_event WHERE student=? GROUP BY outcome",
            (student,)).fetchall()
        tally = {e["outcome"]: e["n"] for e in events}
        return {"student": student, "concepts": rows,
                "attempts": sum(tally.values()),
                "passed": tally.get("pass", 0), "failed": tally.get("fail", 0)}
    finally:
        con.close()


def record_attempt(student: str, problem_slug: str, solved: bool,
                   fault_sig: Optional[str] = None,
                   now: Optional[float] = None) -> dict:
    """THE RETURN EDGE. Fold one attempt back into the student's mastery state.

    Two channels, deliberately different in strength:

      * every concept the problem exercises is recorded pass/fail. This is the
        broad, always-available signal.
      * if Bisect PROVED a specific fault signature, `blame` maps it to the one
        concept the defect actually implicates, and that concept is decayed on
        evidence rather than on association.

    The second is why the engine bothers proving anything. A judge can tell you a
    submission failed; only a proof can tell you WHICH idea you got wrong, and
    that is the difference between "practise arrays again" and "your range
    semantics are off".
    """
    now = now or time.time()
    d = ROOT / "problems" / problem_slug
    meta = json.loads((d / "problem.json").read_text(encoding="utf-8"))
    concepts = [c["id"] for c in meta.get("concepts", [])]
    con = kn.connect(DB)
    try:
        for c in concepts:
            kn.record(con, student, c, solved,
                      source=f"submission:{problem_slug}", now=now)
        blamed, suspects = None, []
        if not solved and fault_sig:
            b = kn.blame(con, student, fault_sig=fault_sig,
                         problem_concepts=concepts, now=now)
            # `mapped` is the concept an EXACT fault-signature row implicates —
            # evidence. `suggested` is a semantic-similarity guess and is only
            # ever a suggestion, never grounds to decay anything (see
            # semantic.py: vectors suggest, the table decides).
            blamed = b.get("mapped")
            suspects = [s["concept"] for s in b.get("suspects", [])][:3]
            if blamed:
                kn.record(con, student, blamed, False, source="proven-fault", now=now)
        return {"recorded": concepts, "solved": solved,
                "blamed": blamed, "suspects": suspects}
    finally:
        con.close()
