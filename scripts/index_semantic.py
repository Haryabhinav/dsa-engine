"""Build the Qdrant semantic index from SQLite + the problem bundles."""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "analysis"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import knowledge as kn
import semantic as sem

# Fault signatures described in prose so an unseen mutation delta can be matched
# by resemblance. Authored deliberately: the phrasing is what gets embedded, so
# it must describe the DEFECT, not the syntax.
MISCONCEPTIONS = [
    ("cmp:<=->:<", "range-semantics",
     "an inclusive comparison where an exclusive one was needed; a boundary is "
     "counted that should have been excluded; an element paired with itself"),
    ("cmp:<->:<=", "range-semantics",
     "an exclusive comparison where an inclusive one was needed; the final "
     "element or boundary case is skipped"),
    ("cmp:>=->:>", "range-semantics",
     "off by one at an upper bound; the loop stops one iteration early or late"),
    ("cmp:==->:!=", "comparator-semantics",
     "equality confused with inequality; a comparator that is not a strict weak "
     "ordering; ties handled the wrong way round"),
    ("const:off1", "loop-invariants",
     "a loop bound or index constant off by one; starting at the wrong index; "
     "an accumulator initialised to the wrong value"),
    ("bin:+->:-", "prefix-sums",
     "addition and subtraction transposed in a running total or prefix sum"),
    ("bool:and->:or", "loop-invariants",
     "a conjunction written where a disjunction was meant; a guard condition "
     "that admits cases it should reject"),
    ("dup:double-count", "duplicate-handling",
     "each pair counted twice; duplicates not deduplicated; an element matched "
     "against itself when it should not be"),
    ("visit:mark-late", "visited-marking",
     "a node marked visited when popped rather than when pushed, so it enters "
     "the queue more than once"),
    ("overflow:int", "integer-overflow",
     "a value exceeding 32-bit range; a product or sum overflowing before it is "
     "stored in a wider type"),
]


def main() -> int:
    qc = sem.client()
    con = kn.connect(ROOT / "knowledge.db")

    concepts = [dict(r) for r in con.execute(
        "SELECT id, name, description FROM concept")]
    n_c = sem.index_concepts(qc, concepts)

    metas = []
    for d in sorted((ROOT / "problems").iterdir()):
        f = d / "problem.json"
        if f.exists():
            metas.append(json.loads(f.read_text(encoding="utf-8")))
    n_p = sem.index_problems(qc, metas)

    n_m = sem.index_misconceptions(
        qc, [{"sig": s, "concept": c, "text": t} for s, c, t in MISCONCEPTIONS])

    print(f"indexed into {sem.STORE}")
    print(f"  concepts       {n_c}")
    print(f"  problems       {n_p}")
    print(f"  misconceptions {n_m}")
    print(f"  counts         {sem.stats(qc)}")
    qc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
