"""Halflife & Syllabus — concept DAG, coupled decay, review scheduling.

The premise: spaced repetition treats every item independently, so a rotting
prerequisite silently invalidates everything built on it. Here retrievability is
COUPLED along prerequisite edges, which changes what the optimal next review is.

Storage goes through `store.Store`, which speaks SQLite in development and
Postgres in deployment. The switch is `DSA_DATABASE_URL`; the threshold is more
than one application host, because SQLite is a file and two app servers cannot
safely share one.

(An earlier version of this docstring claimed the migration was "a
connection-string change plus a closure-table refresh". That was an overclaim --
four genuine dialect incompatibilities had to be solved. See store.py.)
"""
from __future__ import annotations

import math
import pathlib
import time
from dataclasses import dataclass
from typing import Iterable, Optional

DAY = 86400.0

def connect(path: str | pathlib.Path = "knowledge.db", dsn: Optional[str] = None):
    """SQLite by default; Postgres when DSA_DATABASE_URL (or `dsn`) is set."""
    from store import Store
    return Store(dsn=dsn, path=path)


# --------------------------------------------------------------------------
# Graph hygiene: SCC condensation, then transitive reduction.
# Both are correctness requirements, not optimisations.
# --------------------------------------------------------------------------
def _edges(con) -> list[tuple[str, str]]:
    return [(r["parent"], r["child"]) for r in
            con.execute("SELECT parent, child FROM concept_edge "
                        "WHERE kind='PREREQUISITE_OF'")]


def tarjan_scc(nodes: list[str], edges: list[tuple[str, str]]) -> dict[str, str]:
    """Real curricula contain mutual prerequisites (you need some algebra to
    learn functions and some functions to learn algebra). Propagating over a
    graph with cycles never terminates, so collapse each cycle to a super-node
    and propagate over the condensation, which IS a DAG."""
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for u, v in edges:
        if u in adj:
            adj[u].append(v)

    index = {}
    low = {}
    on = {}
    stack: list[str] = []
    counter = [0]
    comp: dict[str, str] = {}

    def strongconnect(root: str) -> None:
        work = [(root, 0)]
        while work:
            v, pi = work[-1]
            if pi == 0:
                index[v] = low[v] = counter[0]
                counter[0] += 1
                stack.append(v)
                on[v] = True
            recurse = False
            for i in range(pi, len(adj[v])):
                w = adj[v][i]
                if w not in index:
                    work[-1] = (v, i + 1)
                    work.append((w, 0))
                    recurse = True
                    break
                elif on.get(w):
                    low[v] = min(low[v], index[w])
            if recurse:
                continue
            if low[v] == index[v]:
                members = []
                while True:
                    w = stack.pop()
                    on[w] = False
                    members.append(w)
                    if w == v:
                        break
                cid = min(members)
                for m in members:
                    comp[m] = cid
            work.pop()
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])

    for n in nodes:
        if n not in index:
            strongconnect(n)
    return comp


def transitive_reduction(nodes: list[str], edges: list[tuple[str, str]]) -> set[tuple[str, str]]:
    """Mark edges implied by a longer path. Without this, A->B->D plus A->D
    counts A's decay TWICE and systematically under-reports deep concepts."""
    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for u, v in edges:
        if u in adj:
            adj[u].add(v)

    reach: dict[str, set[str]] = {}

    def descendants(u: str, seen: set[str]) -> set[str]:
        if u in reach:
            return reach[u]
        if u in seen:
            return set()
        seen.add(u)
        out: set[str] = set()
        for w in adj.get(u, ()):
            out.add(w)
            out |= descendants(w, seen)
        reach[u] = out
        return out

    redundant: set[tuple[str, str]] = set()
    for u, v in edges:
        # v reachable from u without using the direct edge?
        via = set()
        for w in adj.get(u, ()):
            if w != v:
                via.add(w)
                via |= descendants(w, set())
        if v in via:
            redundant.add((u, v))
    return redundant


def rebuild_graph(con) -> dict:
    """Condense cycles, mark redundant edges, rebuild the closure table."""
    nodes = [r["id"] for r in con.execute("SELECT id FROM concept")]
    edges = _edges(con)

    scc = tarjan_scc(nodes, edges)
    for n in nodes:
        con.execute("UPDATE concept SET scc_id=? WHERE id=?", (scc.get(n, n), n))

    redundant = transitive_reduction(nodes, edges)
    con.execute("UPDATE concept_edge SET redundant=0")
    for u, v in redundant:
        con.execute("UPDATE concept_edge SET redundant=1 WHERE parent=? AND child=?", (u, v))

    kept = [(u, v) for (u, v) in edges if (u, v) not in redundant]
    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for u, v in kept:
        adj[u].add(v)

    con.execute("DELETE FROM concept_closure")
    for src in nodes:
        seen = {src: 0}
        frontier = [src]
        d = 0
        while frontier:
            d += 1
            nxt = []
            for u in frontier:
                for w in adj.get(u, ()):
                    if w not in seen:
                        seen[w] = d
                        nxt.append(w)
            frontier = nxt
        for dst, depth in seen.items():
            if dst != src:
                con.upsert("concept_closure",
                           ["ancestor", "descendant"],
                           {"ancestor": src, "descendant": dst, "depth": depth})
    con.commit()
    cycles = len(nodes) - len(set(scc.values()))
    return {"nodes": len(nodes), "edges": len(edges),
            "redundant": len(redundant), "in_cycles": cycles}


# --------------------------------------------------------------------------
# Coupled decay
# --------------------------------------------------------------------------
ALPHA = 0.6          # damping on the weakest-link penalty


@dataclass
class Retrievability:
    own: dict[str, float]
    eff: dict[str, float]


def _topo(nodes: list[str], parents: dict[str, list[str]]) -> list[str]:
    indeg = {n: len(parents.get(n, [])) for n in nodes}
    q = [n for n in nodes if indeg[n] == 0]
    order, i = [], 0
    children: dict[str, list[str]] = {n: [] for n in nodes}
    for c, ps in parents.items():
        for p in ps:
            children.setdefault(p, []).append(c)
    while i < len(q):
        u = q[i]; i += 1
        order.append(u)
        for c in children.get(u, ()):
            indeg[c] -= 1
            if indeg[c] == 0:
                q.append(c)
    order += [n for n in nodes if n not in set(order)]     # cycle remnants
    return order


def retrievability(con, student: str, now: Optional[float] = None,
                   refresh: Optional[str] = None) -> Retrievability:
    """R_own = 2^(-elapsed / stability); R_eff couples it through prerequisites.

        R_eff(c) = R_own(c) * (1 - ALPHA * (1 - min_p R_eff(p)))

    Damped weakest-link: a chain is as strong as its weakest link, but damping
    stops deep concepts collapsing to zero merely for having many ancestors.
    """
    now = now or time.time()
    nodes = [r["id"] for r in con.execute("SELECT id FROM concept")]
    parents: dict[str, list[str]] = {n: [] for n in nodes}
    for r in con.execute("SELECT parent, child FROM concept_edge "
                         "WHERE kind='PREREQUISITE_OF' AND redundant=0"):
        parents[r["child"]].append(r["parent"])

    own: dict[str, float] = {}
    seen_set: set[str] = set()
    for n in nodes:
        row = con.execute("SELECT stability, last_review, seen FROM mastery "
                          "WHERE student=? AND concept=?", (student, n)).fetchone()
        if row is not None and row["seen"]:
            seen_set.add(n)
        if n == refresh:
            own[n] = 1.0
        elif row is None or not row["seen"]:
            own[n] = 0.0
        else:
            elapsed = max(0.0, (now - row["last_review"]) / DAY)
            own[n] = 2 ** (-elapsed / max(row["stability"], 0.1))

    eff: dict[str, float] = {}
    for n in _topo(nodes, parents):
        # UNSEEN PREREQUISITES ARE UNKNOWN, NOT WEAK. An unseen concept has
        # own = 0.0, and feeding that into the weakest-link min penalised a
        # student maximally for topics they had never been taught: a learner who
        # had just PROVEN they can write merge sort was shown 0.40 effective
        # retention because `recursion` and `binary-search` were still blank
        # (BUILD_LOG F48).
        #
        # Absence of evidence is not evidence of weakness, and this is the same
        # correction F20 forced on the lift calculation — applied one layer down,
        # to retention itself, where it was still wrong.
        ps = [p for p in parents.get(n, []) if p in seen_set or p == refresh]
        if not ps:
            eff[n] = own[n]
        else:
            weakest = min(eff.get(p, own.get(p, 0.0)) for p in ps)
            eff[n] = own[n] * (1.0 - ALPHA * (1.0 - weakest))
    return Retrievability(own, eff)


# --------------------------------------------------------------------------
# Scheduling: value a review by TOTAL lift, not by due-ness
# --------------------------------------------------------------------------
@dataclass
class ReviewCandidate:
    concept: str
    name: str
    own: float
    eff: float
    self_lift: float          # gain on the concept itself
    downstream_lift: float    # gain on everything built on top of it
    lifts_n: int

    @property
    def lift(self) -> float:
        return self.self_lift + self.downstream_lift


def review_queue(con, student: str, now: Optional[float] = None,
                 limit: int = 8, include_unseen: bool = False) -> list[ReviewCandidate]:
    """The highest-value review is not the most-due item — it is the one whose
    refresh raises effective retrievability the most across everything built on
    top of it. One review of a foundation can outrank three reviews of the
    leaves that depend on it.

    Two corrections learned by running this (BUILD_LOG F12):

    * **Rank by TOTAL lift (self + downstream); report the two parts
      separately.** Ranking by downstream lift ALONE starves leaves: a leaf has
      zero downstream lift by definition, so Dijkstra itself would never be
      scheduled. The calibration simulator measured this directly — retention
      collapsed to 0.46 against 0.998 for classical SRS (BUILD_LOG F20). The
      genuine fix for cold-start distortion was the unseen-concept filter below,
      not discarding self-lift.
    * **Never-seen concepts are excluded by default.** You cannot *review*
      something you never learned — that is a learning queue, and mixing the two
      makes the review queue meaningless during cold start.
    """
    now = now or time.time()
    base = retrievability(con, student, now)
    rows = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM concept")}
    seen = {r["concept"] for r in
            con.execute("SELECT concept FROM mastery WHERE student=? AND seen=1", (student,))}

    out: list[ReviewCandidate] = []
    for cid, name in rows.items():
        if not include_unseen and cid not in seen:
            continue
        after = retrievability(con, student, now, refresh=cid)
        self_lift = after.eff[cid] - base.eff[cid]
        downstream = sum(after.eff[k] - base.eff[k] for k in base.eff if k != cid)
        touched = sum(1 for k in base.eff
                      if after.eff[k] - base.eff[k] > 1e-9 and k != cid)
        out.append(ReviewCandidate(cid, name, base.own[cid], base.eff[cid],
                                   self_lift, downstream, touched))
    out.sort(key=lambda c: (-(c.self_lift + c.downstream_lift), -c.downstream_lift))
    return out[:limit]


# --------------------------------------------------------------------------
# Outcome recording and blame assignment
# --------------------------------------------------------------------------
def record(con, student: str, concept: str, ok: bool, source: str = "submission",
           now: Optional[float] = None) -> None:
    now = now or time.time()
    row = con.execute("SELECT stability FROM mastery WHERE student=? AND concept=?",
                      (student, concept)).fetchone()
    stab = row["stability"] if row else 3.0
    stab = stab * 1.9 if ok else max(1.0, stab * 0.5)
    con.upsert("mastery", ["student", "concept"],
               {"student": student, "concept": concept, "stability": stab,
                "last_review": now, "seen": 1})
    con.execute("INSERT INTO review_event (student, concept, outcome, source, ts) "
                "VALUES (?,?,?,?,?)",
                (student, concept, "pass" if ok else "fail", source, now))
    con.commit()


def blame(con, student: str, fault_sig: Optional[str] = None,
          problem_concepts: Optional[Iterable[str]] = None,
          now: Optional[float] = None,
          fault_desc: Optional[str] = None) -> dict:
    """Attribute a failure. Takes TWO inputs, not one (BUILD_LOG F13):

    * `fault_sig` — the proven mutation signature from Bisect. Its mapped
      concept is decayed directly, because that attribution is evidence-backed.
    * `problem_concepts` — what the problem itself exercises. A `<=` bug inside
      a Dijkstra problem is evidence about range semantics, but the *context* is
      Dijkstra, and the weak ancestors worth suspecting live above Dijkstra —
      priority queues, heaps — not above range-semantics (which is a root and
      has none).

    Ancestors are only ever marked SUSPECT, never decayed. Misattribution
    corrupts scheduling permanently and invisibly, so an ancestor is decayed
    only once a discriminating probe confirms it.
    """
    now = now or time.time()
    mapped = None
    suggested = None
    if fault_sig:
        row = con.execute("SELECT concept FROM fault_signature WHERE sig=?",
                          (fault_sig,)).fetchone()
        if row:
            mapped = row["concept"]
            record(con, student, mapped, ok=False, source="bisect", now=now)
        else:
            # No exact row. Fall back to the semantic layer -- but ONLY as a
            # suggestion. VECTORS SUGGEST, SQLITE DECIDES: a similarity score is
            # evidence of resemblance, never of identity, and a wrong mapping
            # corrupts a student's schedule invisibly and permanently. Nothing
            # is decayed on this path; a human must ratify it into
            # `fault_signature` first.
            #
            # The query must be PROSE, not the signature slug. Measured against
            # the same index: "visit:mark-on-pop-not-push" scores 0.731 (below
            # floor, no suggestion) while "a node is marked visited when it is
            # popped rather than when it is pushed" scores 0.909. The register
            # of the query has to match the register of what was indexed.
            # With no description available we ask NOTHING -- a bad query is
            # worse than no query, because it returns a plausible wrong answer.
            try:
                if not fault_desc:
                    raise ValueError("no prose description; not querying")
                import semantic as sem
                qc = sem.client()
                hits = sem.suggest_misconception(qc, fault_desc, k=1)
                qc.close()
                if hits:
                    suggested = {"concept": hits[0].payload.get("concept_id"),
                                 "score": round(hits[0].score, 3),
                                 "requires_confirmation": True}
            except Exception:
                suggested = None            # semantic layer is optional, never load-bearing

    roots = list(problem_concepts or ([mapped] if mapped else []))
    if not roots:
        return {"mapped": None, "suggested": suggested, "suspects": []}

    r = retrievability(con, student, now)
    seen_sus: dict[str, dict] = {}
    for root in roots:
        for a in con.execute("SELECT ancestor, depth FROM concept_closure "
                             "WHERE descendant=? ORDER BY depth", (root,)):
            cid = a["ancestor"]
            if cid == mapped or cid in seen_sus:
                continue
            own = r.own.get(cid, 0.0)
            if own < 0.6:
                seen_sus[cid] = {"concept": cid, "depth": a["depth"],
                                 "own_r": round(own, 3), "under": root}
    # Rank by PROXIMITY first, weakness second (BUILD_LOG F14). Sorting by
    # own_r alone surfaces the most-rotted node in the whole graph, which is
    # invariably a deep root — nobody's Dijkstra failure is usefully answered
    # with "revise loops and iteration". The nearest weak prerequisite is the
    # actionable one, and it is the one a discriminating probe should target.
    suspects = sorted(seen_sus.values(), key=lambda s: (s["depth"], s["own_r"]))
    return {"mapped": mapped, "suggested": suggested, "suspects": suspects[:6]}
