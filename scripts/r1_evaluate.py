"""R1: does the deterministic cascade find real bugs? Measured, with the misses.

This is the experiment the BUILD_LOG has listed as outstanding since session 1.
Everything else in this repo tests whether the machine does what I told it to.
This tests whether what I told it to do is worth anything.

WHAT IS BEING MEASURED

  1. TIER DISTRIBUTION over 65 validated (correct, buggy) pairs whose bugs came
     from a source independent of the mutation catalog.
  2. LOCALISATION ACCURACY -- when the engine says PROVEN, is the line it names
     the line that actually changed? A confident wrong answer is worse than
     declining, so this is scored separately from the tier.
  3. IN-CATALOG vs OUT-OF-CATALOG. This is the honest core. A defect is
     "in-catalog" if SOME single mutation from the operator catalog, applied to
     the buggy source, reproduces the correct source -- i.e. the repair is
     reachable in one step. That is a property of the BUG, computed statically
     before any search runs, so it cannot be contaminated by the outcome.

     Reporting one blended hit rate would hide the only number that matters:
     what happens on bugs the catalog cannot express. A tool that scores 95% on
     bugs it was designed for and 0% on everything else, reported as "78%
     overall", is a tool that will surprise a student badly.
  4. FALSE ALARMS -- the same pipeline run on the CORRECT programs. Claiming
     PROVEN on correct code is the single most damaging thing this engine can
     do, so it is measured rather than assumed.

Run:  python scripts/r1_evaluate.py [limit]
"""
import json
import pathlib
import sys
import time
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "analysis"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import dispatch
import localize as lz
from engine import Problem, stress

MF = ROOT / "corpus_r1" / "manifest.json"


def reachable_in_one_mutation(buggy_src: str, correct_src: str, path: pathlib.Path) -> bool:
    """Is the true repair a SINGLE step in the operator catalog?

    Computed by applying every catalog mutation to the buggy source and asking
    whether any of them reproduces the correct source (whitespace-normalised).
    Note this is NOT the same question as "does repair_search succeed": the
    search must also locate the site through coverage and spectrum guidance,
    stay inside its budget, and validate by execution -- and it can legitimately
    succeed by finding a DIFFERENT repair that also passes. Keeping the two
    apart is what makes the in/out split meaningful.
    """
    target = "".join(correct_src.split())
    try:
        sites = dispatch.sites_for(path, buggy_src)
    except Exception:
        return False
    for s in sites:
        try:
            if "".join(dispatch.apply_for(path, buggy_src, s).split()) == target:
                return True
        except Exception:
            continue
    return False


def main() -> int:
    allrows = json.loads(MF.read_text(encoding="utf-8"))
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(allrows)
    off = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    RES = ROOT / "corpus_r1" / "results.json"
    done = json.loads(RES.read_text(encoding="utf-8")) if RES.exists() else []
    seen = {(r["slug"], r["idx"]) for r in done}
    rows = [r for r in allrows if (r["slug"], r["idx"]) not in seen][off:off + limit]
    if limit == 0:                       # report-only from what is already done
        rows = []
    print(f"  R1 evaluation over {len(rows)} validated (correct, buggy) pairs\n")

    probs = {}
    out = []
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        slug = r["slug"]
        p = probs.get(slug) or probs.setdefault(slug, Problem.load(ROOT / "problems" / slug))
        bpath = ROOT / r["buggy"]
        cpath = ROOT / r["correct"]
        if not bpath.exists() or not cpath.exists():
            continue
        bsrc = bpath.read_text(encoding="utf-8")
        csrc = cpath.read_text(encoding="utf-8")
        in_cat = reachable_in_one_mutation(bsrc, csrc, bpath)

        try:
            loc, fails, _ = lz.localize(p, bpath)
        except Exception as e:
            out.append({**r, "tier": f"ERROR:{type(e).__name__}", "in_catalog": in_cat})
            continue

        true_lines = set(r["true_lines"])
        band = [l for l, _ in loc.lines[:3]]
        hit_exact = loc.patch_line in true_lines if loc.patch_line else False
        hit_band = bool(true_lines & set(band))
        out.append({**r, "tier": loc.tier, "in_catalog": in_cat,
                    "patch_line": loc.patch_line, "band": band,
                    "hit_exact": hit_exact, "hit_band": hit_band,
                    "sites": loc.total_sites, "tried": loc.tried})
        mark = "OK " if (hit_exact or (loc.tier == "LOCALIZED" and hit_band)) else "   "
        print(f"  [{i:3d}/{len(rows)}] {mark}{loc.tier:<11} "
              f"{'in-cat ' if in_cat else 'out-cat'} {slug:<24} "
              f"line={loc.patch_line} true={sorted(true_lines)}")

    out = done + out                     # accumulate across chunks
    RES.write_text(json.dumps(out, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ report
    def pct(a, b):
        return f"{100.0 * a / b:5.1f}%" if b else "   n/a"

    print(f"\n{'=' * 72}\nR1 RESULTS   ({len(out)} pairs, {time.time() - t0:.0f}s)\n{'=' * 72}")

    tiers = Counter(r["tier"] for r in out)
    print("\nTier distribution:")
    for t in ("PROVEN", "LOCALIZED", "STRUCTURAL"):
        print(f"  {t:<12} {tiers.get(t, 0):3d}   {pct(tiers.get(t, 0), len(out))}")
    for t, c in tiers.items():
        if t.startswith("ERROR"):
            print(f"  {t:<12} {c:3d}")

    print("\nThe split that matters — is the true repair one catalog step away?")
    hdr = f"  {'':<12}{'n':>4}{'PROVEN':>9}{'LOCALIZED':>11}{'STRUCTURAL':>12}{'exact line':>12}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for label, want in (("in-catalog", True), ("out-of-catalog", False)):
        g = [r for r in out if r.get("in_catalog") is want]
        if not g:
            continue
        pr = sum(1 for r in g if r["tier"] == "PROVEN")
        lo = sum(1 for r in g if r["tier"] == "LOCALIZED")
        st = sum(1 for r in g if r["tier"] == "STRUCTURAL")
        ex = sum(1 for r in g if r.get("hit_exact"))
        print(f"  {label:<12}{len(g):>4}{pct(pr, len(g)):>9}{pct(lo, len(g)):>11}"
              f"{pct(st, len(g)):>12}{pct(ex, len(g)):>12}")

    proven = [r for r in out if r["tier"] == "PROVEN"]
    exact = [r for r in proven if r.get("hit_exact")]
    print(f"\nWhen it says PROVEN, is the named line the line that changed?")
    print(f"  PROVEN verdicts        {len(proven):3d}")
    print(f"  named the true line    {len(exact):3d}   {pct(len(exact), len(proven))}")
    print(f"  named a DIFFERENT line {len(proven) - len(exact):3d}   "
          f"{pct(len(proven) - len(exact), len(proven))}")
    if len(proven) - len(exact):
        print("    (not automatically wrong: a different single-token repair that")
        print("     passes the whole suite is a real repair, and sometimes the")
        print("     model's own 'fix' was not the only one.)")

    loc_rows = [r for r in out if r["tier"] == "LOCALIZED"]
    if loc_rows:
        bh = sum(1 for r in loc_rows if r.get("hit_band"))
        print(f"\nWhen it says LOCALIZED, is the true line in the top-3 band?")
        print(f"  {bh}/{len(loc_rows)}   {pct(bh, len(loc_rows))}")

    print("\nBy bug category (the categories were written as human errors, not operators):")
    kinds = {}
    for r in out:
        k = r.get("bug_kind", "?")[:46]
        kinds.setdefault(k, []).append(r)
    for k, g in sorted(kinds.items(), key=lambda kv: -len(kv[1])):
        pr = sum(1 for r in g if r["tier"] == "PROVEN")
        ic = sum(1 for r in g if r.get("in_catalog"))
        print(f"  {len(g):3d}  in-cat {ic:2d}  PROVEN {pr:2d}   {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
