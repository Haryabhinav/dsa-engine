"""Calibration simulator — does coupled scheduling actually beat independent SRS?

This is the outstanding validation flagged at the end of session 2. Until it
exists, coupled decay is a well-reasoned hypothesis, not a proven improvement.

Method
------
Simulate learners with a GROUND-TRUTH memory model in which prerequisite rot
genuinely damages dependent recall (that is the premise under test). Two
schedulers then compete under an identical daily review budget:

  * INDEPENDENT — classical SRS: review whatever is most decayed on its own.
  * COUPLED     — the review that lifts total effective retention the most
                  (self + downstream; downstream-only starves leaves).

Report retention at horizon AND calibration error, because a scheduler that
merely reviews more is not better — one that knows what it does not know is.

Honest framing: the ground truth here embeds the coupling assumption. That makes
this a test of "given prerequisites matter, does modelling them help?", NOT
evidence that prerequisites matter in real humans. The latter needs real learners
and is out of scope.
"""
from __future__ import annotations

import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "analysis"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import knowledge as kn

ALPHA = 0.6
HORIZON_DAYS = 180
DAILY_BUDGET = 3
N_LEARNERS = 30


def load_graph():
    con = kn.connect(ROOT / "knowledge.db")
    nodes = [r["id"] for r in con.execute("SELECT id FROM concept")]
    parents = {n: [] for n in nodes}
    for r in con.execute("SELECT parent, child FROM concept_edge "
                         "WHERE kind='PREREQUISITE_OF' AND redundant=0"):
        parents[r["child"]].append(r["parent"])
    order = kn._topo(nodes, parents)
    return nodes, parents, order


def true_eff(own: dict, parents: dict, order: list) -> dict:
    """Ground truth: coupling is REAL in the simulated world."""
    eff = {}
    for n in order:
        ps = parents.get(n, [])
        eff[n] = own[n] if not ps else own[n] * (
            1.0 - ALPHA * (1.0 - min(eff.get(p, own[p]) for p in ps)))
    return eff


def simulate(policy: str, seed: int, nodes, parents, order, budget: int = 3) -> dict:
    rng = random.Random(seed)
    stab = {n: rng.uniform(4.0, 12.0) for n in nodes}
    last = {n: -rng.uniform(0, 30.0) for n in nodes}
    predicted_vs_actual: list[tuple[float, int]] = []

    for day in range(HORIZON_DAYS):
        own = {n: 2 ** (-max(0.0, day - last[n]) / stab[n]) for n in nodes}
        eff = true_eff(own, parents, order)

        if policy == "independent":
            # classical: whatever looks most decayed on its own
            picks = sorted(nodes, key=lambda n: own[n])[:budget]
            belief = own                      # believes own == truth
        else:
            # coupled: greatest downstream lift, computed on the model's own view
            model_eff = true_eff(own, parents, order)
            scored = []
            for c in nodes:
                bumped = dict(own)
                bumped[c] = 1.0
                after = true_eff(bumped, parents, order)
                scored.append((sum(after[k] - model_eff[k] for k in nodes), c))
            scored.sort(reverse=True)
            picks = [c for _, c in scored[:budget]]
            belief = model_eff

        # a quiz on 5 random concepts: does belief predict actual recall?
        for n in rng.sample(nodes, 5):
            recalled = 1 if rng.random() < eff[n] else 0
            predicted_vs_actual.append((belief[n], recalled))

        for c in picks:
            last[c] = day
            stab[c] *= 1.6

    own = {n: 2 ** (-max(0.0, HORIZON_DAYS - last[n]) / stab[n]) for n in nodes}
    eff = true_eff(own, parents, order)
    retention = sum(eff.values()) / len(eff)

    # calibration: mean |predicted - observed| in 5 probability bins (Brier-like)
    bins: dict[int, list[tuple[float, int]]] = {}
    for pr, act in predicted_vs_actual:
        bins.setdefault(min(4, int(pr * 5)), []).append((pr, act))
    ece = 0.0
    for b, rows in bins.items():
        mp = sum(r[0] for r in rows) / len(rows)
        ma = sum(r[1] for r in rows) / len(rows)
        ece += abs(mp - ma) * len(rows) / len(predicted_vs_actual)
    return {"retention": retention, "ece": ece}


def depth_of(nodes, parents) -> dict:
    d = {}
    def rec(n, seen):
        if n in d:
            return d[n]
        if n in seen:
            return 0
        seen.add(n)
        ps = parents.get(n, [])
        d[n] = 0 if not ps else 1 + max(rec(p, seen) for p in ps)
        return d[n]
    for n in nodes:
        rec(n, set())
    return d


def main():
    nodes, parents, order = load_graph()
    depths = depth_of(nodes, parents)
    print(f"\ngraph: {len(nodes)} concepts, max prerequisite depth {max(depths.values())}")
    print(f"sim:   {N_LEARNERS} learners x {HORIZON_DAYS} days, "
          f"{DAILY_BUDGET} reviews/day\n")

    print(f"  {"budget":>7}{"indep ret":>11}{"coupl ret":>11}{"delta":>9}"
          f"{"wins":>7}{"indep ECE":>11}{"coupl ECE":>11}{"ECE gain":>10}")
    for budget in (1, 2, 3, 5):
        res = {"independent": [], "coupled": []}
        for seed in range(N_LEARNERS):
            for pol in res:
                res[pol].append(simulate(pol, seed, nodes, parents, order, budget))
        m = lambda p, k: sum(r[k] for r in res[p]) / len(res[p])
        w = sum(1 for a, b in zip(res["coupled"], res["independent"])
                if a["retention"] > b["retention"])
        dr = m("coupled", "retention") - m("independent", "retention")
        eg = (m("independent", "ece") - m("coupled", "ece")) / max(m("independent", "ece"), 1e-9)
        print(f"  {budget:>7}{m("independent","retention"):>11.4f}{m("coupled","retention"):>11.4f}"
              f"{dr:>+9.4f}{w:>5}/{N_LEARNERS}{m("independent","ece"):>11.4f}"
              f"{m("coupled","ece"):>11.4f}{eg:>9.1%}")
    print()
    res = {"independent": [], "coupled": []}
    for seed in range(N_LEARNERS):
        for pol in res:
            res[pol].append(simulate(pol, seed, nodes, parents, order, DAILY_BUDGET))

    def mean(pol, key):
        return sum(r[key] for r in res[pol]) / len(res[pol])

    print(f"  {'policy':<14}{'retention':>11}{'calib. error':>15}")
    for pol in ("independent", "coupled"):
        print(f"  {pol:<14}{mean(pol,'retention'):>11.4f}{mean(pol,'ece'):>15.4f}")

    dr = (mean("coupled", "retention") - mean("independent", "retention"))
    de = (mean("independent", "ece") - mean("coupled", "ece"))
    rel_r = dr / mean("independent", "retention") * 100
    rel_e = de / max(mean("independent", "ece"), 1e-9) * 100

    wins = sum(1 for a, b in zip(res["coupled"], res["independent"])
               if a["retention"] > b["retention"])
    print(f"\n  retention   {dr:+.4f}  ({rel_r:+.1f}%)   coupled wins {wins}/{N_LEARNERS} learners")
    print(f"  calibration {de:+.4f}  ({rel_e:+.1f}% lower error)")

    verdict = ("coupled scheduling helps" if dr > 0.005 and wins > N_LEARNERS * 0.6
               else "NO RELIABLE IMPROVEMENT — do not claim one")
    print(f"\n  verdict: {verdict}")
    print("\n  caveat: ground truth here assumes coupling is real. This tests")
    print("  'does modelling it help?', not 'is it true of humans?'.")


if __name__ == "__main__":
    main()
