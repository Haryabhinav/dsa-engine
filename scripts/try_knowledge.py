"""Demonstrate coupled decay: the thing independent spaced repetition cannot see."""
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "analysis"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import knowledge as kn

DAY = kn.DAY
NOW = 1_700_000_000.0          # fixed clock so the demo is reproducible
S = "student-1"

con = kn.connect(ROOT / "knowledge.db")
con.execute("DELETE FROM mastery"); con.execute("DELETE FROM review_event"); con.commit()

# A realistic profile: foundations learned long ago, Dijkstra drilled recently.
learned = {
    "variables-loops": 90, "arrays-indexing": 85, "range-semantics": 80,
    "comparison-operators": 80, "hashing": 70, "hash-lookup": 70,
    "graph-representation": 40, "queues": 45, "stacks": 45,
    "heaps": 30, "priority-queue": 28, "bfs": 20, "dfs": 20,
    "visited-marking": 15, "shortest-path-unweighted": 12,
    "recursion": 60, "loop-invariants": 55, "sorting": 50,
    "dijkstra": 3,                      # drilled three days ago
}
for cid, days_ago in learned.items():
    # con.upsert, not raw `INSERT OR REPLACE` — that syntax is SQLite-only and
    # this line is exactly how a "portable" migration stays broken: the Store
    # abstraction was added, every module was moved onto it, and one script kept
    # its own SQL and passed on SQLite forever (BUILD_LOG F32).
    con.upsert("mastery", ["student", "concept"],
               {"student": S, "concept": cid, "stability": 9.0,
                "last_review": NOW - days_ago * DAY, "seen": 1})
con.commit()

r = kn.retrievability(con, S, NOW)
names = {x["id"]: x["name"] for x in con.execute("SELECT id, name FROM concept")}

print("\n=== Own vs Effective retrievability ===")
print("  (own = classical independent decay · eff = coupled through prerequisites)\n")
print(f"  {'concept':<28}{'own':>7}{'eff':>8}   gap")
watch = ["dijkstra", "priority-queue", "heaps", "visited-marking",
         "shortest-path-unweighted", "graph-representation", "arrays-indexing"]
for cid in watch:
    o, e = r.own[cid], r.eff[cid]
    bar = "#" * int((o - e) * 40)
    print(f"  {names[cid]:<28}{o:>7.2f}{e:>8.2f}   {bar}")

print("\n  Dijkstra was reviewed 3 days ago, so independent SRS believes it is")
print(f"  {r.own['dijkstra']:.0%} retained and would not schedule it. Coupled through its")
print(f"  rotted prerequisites the real figure is {r.eff['dijkstra']:.0%}.")

print("\n=== Review queue — ranked by total lift, not by due-ness ===\n")
print(f"  {'#':<3}{'concept':<28}{'own':>6}{'eff':>7}{'self':>7}{'down':>7}   why")
for i, c in enumerate(kn.review_queue(con, S, NOW, limit=6), 1):
    print(f"  {i:<3}{c.name:<28}{c.own:>6.2f}{c.eff:>7.2f}{c.self_lift:>7.2f}"
          f"{c.downstream_lift:>7.2f}   lifts {c.lifts_n} downstream topics")

print("\n=== Blame assignment — the stated Dijkstra example ===\n")
res = kn.blame(con, S, "cmp:<=->:<", problem_concepts=["dijkstra"], now=NOW)
print("  scenario: a '<=' bug proven by Bisect, inside a Dijkstra problem")
print(f"  decayed (evidence-backed): {res['mapped']}")
print("  ancestors marked SUSPECT (not decayed — a probe must confirm first):")
for s2 in res["suspects"]:
    print(f"    depth {s2['depth']}  {names[s2['concept']]:<26} own_r={s2['own_r']}")

r2 = kn.retrievability(con, S, NOW)
print(f"\n  effect on Dijkstra: eff {r.eff['dijkstra']:.3f} -> {r2.eff['dijkstra']:.3f}")
