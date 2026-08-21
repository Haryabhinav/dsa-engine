"""Exercise the semantic layer — including the cases where it should say nothing."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "analysis"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import semantic as sem

qc = sem.client()


def show(title, results, empty_note="(nothing above the similarity floor)"):
    print(f"\n{title}")
    if not results:
        print(f"  {empty_note}")
        return
    for r in results:
        label = r.payload.get("concept_id") or r.payload.get("slug") or r.payload.get("sig")
        print(f"  {r.score:.3f}  {label:<26} confirm={r.requires_confirmation}")


print("=" * 70)
print("1. AUTHORING AID — which concepts does this statement exercise?")
show("  statement: 'Find the shortest route between two cities on a weighted road network.'",
     sem.suggest_concepts(qc,
        "Find the shortest route between two cities on a weighted road network.", k=5))

show("  statement: 'Return the length of the longest run of distinct characters.'",
     sem.suggest_concepts(qc,
        "Return the length of the longest run of distinct characters.", k=5))

print("\n" + "=" * 70)
print("2. MISCONCEPTION FALLBACK — an UNSEEN fault delta, no exact signature row")
show("  delta: 'comparison changed so an index can be paired with itself'",
     sem.suggest_misconception(qc,
        "comparison changed so an index can be paired with itself", k=3))

show("  delta: 'node added to the queue twice because it was marked after popping'",
     sem.suggest_misconception(qc,
        "node added to the queue twice because it was marked after popping", k=3))

print("\n" + "=" * 70)
print("3. NEAR-DUPLICATE DETECTION")
show("  candidate: 'Count index pairs whose values add up to a target.'",
     sem.near_duplicates(qc, "Count index pairs whose values add up to a target.", k=3))

show("  candidate: 'Simulate a bank queue with priority customers.'",
     sem.near_duplicates(qc, "Simulate a bank queue with priority customers.", k=3),
     "(correctly no duplicate — nothing in the bank is close enough)")

print("\n" + "=" * 70)
print("4. THE FLOOR EARNING ITS KEEP — a query with no honest answer")
show("  statement: 'What is the best recipe for sourdough bread?'",
     sem.suggest_concepts(qc, "What is the best recipe for sourdough bread?", k=5),
     "(correctly nothing — cosine ALWAYS returns a nearest neighbour, so without\n"
     "   a similarity floor this would confidently suggest a DSA concept)")

qc.close()  # local mode holds a file handle; closing avoids interpreter-shutdown noise
