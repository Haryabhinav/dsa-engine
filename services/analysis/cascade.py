"""CLI driver for the diagnosis cascade (S0-S4 subset, day 1)."""
from __future__ import annotations

import argparse
import pathlib
import sys

# Windows consoles default to cp1252 and cannot encode box-drawing glyphs.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from engine import (Problem, oracle_gate, stress, shrink_int_array,
                    fit_complexity, run, PY, solution_cmd, language_available)

DIM, B, R, G, Y, X = "\033[2m", "\033[1m", "\033[31m", "\033[32m", "\033[33m", "\033[0m"


def hdr(s):
    print(f"\n{B}{s}{X}\n" + "─" * min(len(s), 70))


def cmd_gate(a):
    p = Problem.load(a.problem)
    hdr(f"S0 · Oracle gate — {p.meta['slug']}")
    g = oracle_gate(p, trials=a.trials)
    for k, v in g.checks.items():
        print(f"  {G+'PASS'+X if v else R+'FAIL'+X}  {k}")
    if g.detail:
        print(f"\n  {Y}{g.detail}{X}")
    print(f"\n  {'TRUSTED' if g.passed else R+'QUARANTINED'+X}")
    return 0 if g.passed else 1


def cmd_diagnose(a):
    p = Problem.load(a.problem)
    sub = pathlib.Path(a.submission)
    print(f"{B}Problem{X} {p.meta['slug']}   {B}Submission{X} {sub.name}")

    # ---- S1 correctness on samples -------------------------------------
    hdr("S1 · Correctness")
    bad = [(i, o, run(solution_cmd(sub), i, 5000).out) for i, o in p.samples()]
    fails = [(i, o, g) for i, o, g in bad if g != o]
    if not fails:
        print(f"  {G}samples pass{X}")
    for i, o, g in fails:
        print(f"  {R}sample failed{X}  expected={o!r} got={g!r}")

    # ---- S2 counterexample + shrink -------------------------------------
    hdr("S2 · Test 42 — minimal counterexample")
    ce = stress(p, sub, max_seeds=a.seeds)
    if ce is None:
        print(f"  {G}no disagreement found in {a.seeds} seeds{X}")
    else:
        print(f"  {DIM}found at seed={ce.seed} n={ce.n}, shrinking…{X}")
        small = shrink_int_array(p, sub, ce)
        chain = " → ".join(str(s) for s in small.shrink_steps) or str(small.n)
        print(f"  shrink: {chain}")
        print(f"\n  {B}minimal input{X}   {small.input.strip().replace(chr(10), ' | ')}")
        print(f"  {B}your output{X}     {R}{small.actual}{X}")
        print(f"  {B}expected{X}        {G}{small.expected}{X}")

    # ---- S3 fault localization -------------------------------------------
    hdr("S3 · Bisect — fault localization")
    import localize as lz
    loc, fails_c, passes_c = lz.localize(p, sub)
    print(f"  {DIM}suite: {len(fails_c)} failing / {len(passes_c)} passing · "
          f"{loc.total_sites} mutation sites, {loc.tried} tried after coverage pruning{X}")
    if not fails_c:
        print(f"  {G}no failing case found — nothing to localize{X}")
    else:
        tier_col = {"PROVEN": G, "LOCALIZED": Y, "STRUCTURAL": DIM}.get(loc.tier, X)
        print(f"  tier: {tier_col}{B}{loc.tier}{X}")
    if loc.tier == "PROVEN":
        print(f"  defect proven at {B}line {loc.patch_line}{X}")
        print(f"  {DIM}[RESTRICTED — never leaves the server: {loc.patch}]{X}")
    elif loc.tier == "LOCALIZED":
        top = loc.lines[:3]
        print(f"  likely within: " + ", ".join(f"L{ln} ({s:.2f})" for ln, s in top))
    elif fails_c:
        print(f"  {DIM}no single-token repair, and the coverage spectrum cannot"
              f" discriminate — refusing to point at a line{X}")

    # ---- S5 robustness gate (only on AC) ---------------------------------
    if not fails_c:
        hdr("S5 · Forge — robustness gate")
        suite = [lz.Case(i, o) for i, o in p.samples()]
        suite += [lz.Case(p.generate(s, 12), p.reference(p.generate(s, 12)).out)
                  for s in range(900, 908)]
        fr = lz.forge(p, sub, suite, budget=40)
        print(f"  mutation score: {B}{fr.score:.2f}{X}  ({fr.killed}/{fr.total} mutants killed)")
        if fr.survived:
            print(f"  {Y}{len(fr.survived)} survived{X} — tested behaviour is under-specified")
            for s in fr.survived[:4]:
                print(f"    {DIM}{s}{X}")
        if fr.latent_bug:
            lb = fr.latent_bug
            print(f"\n  {R}{B}LATENT BUG — the judge never exercised this{X}")
            print(f"    input    {lb['input'].replace(chr(10), ' | ')}")
            print(f"    yours    {R}{lb['actual']}{X}   expected {G}{lb['expected']}{X}")
        status = "MASTERED" if fr.score >= 0.85 and not fr.latent_bug else "PROVISIONAL"
        print(f"\n  status: {B}{status}{X}")

    # ---- S6 knowledge update ---------------------------------------------
    kdb = pathlib.Path(a.problem).resolve().parents[1] / "knowledge.db"
    if kdb.exists() and fails_c:
        hdr("S6 · Halflife — knowledge update")
        import knowledge as kn
        con = kn.connect(kdb)
        pcs = [c["id"] for c in p.meta.get("concepts", [])]
        res = kn.blame(con, a.student, loc.fault_sig, problem_concepts=pcs)
        if res["mapped"]:
            print(f"  decayed (evidence-backed): {B}{res['mapped']}{X}"
                  f"  {DIM}via fault signature {loc.fault_sig}{X}")
        else:
            print(f"  {DIM}no proven fault signature — nothing decayed{X}")
        if res["suspects"]:
            print(f"  {Y}SUSPECT{X} (not decayed — a discriminating probe must confirm):")
            for s in res["suspects"][:4]:
                print(f"    {DIM}depth {s['depth']}{X}  {s['concept']:<26} own_r={s['own_r']}")
        q = kn.review_queue(con, a.student, limit=3)
        if q:
            print("  next reviews by downstream lift:")
            for i, cc in enumerate(q, 1):
                print(f"    {i}. {cc.name:<26} lifts {cc.lifts_n} topics "
                      f"{DIM}(down {cc.downstream_lift:+.2f}){X}")

    # ---- S4 complexity ---------------------------------------------------
    hdr("S4 · Complexity")
    fit = fit_complexity(p, sub, trials=a.trials)
    req = p.meta["required_complexity"]
    for n, t in fit.points:
        print(f"  {DIM}n={n:<6} {t:8.1f} ms{X}")
    print(f"\n  measurement CV: {fit.cv*100:.1f}%"
          + (f"  {Y}(>3% — fits are unreliable){X}" if fit.cv > 0.03 else f"  {G}(stable){X}"))
    if len(fit.points) >= 3:
        print(f"  empirical exponent: {B}k = {fit.exponent:.2f} ± {fit.ci95:.2f}{X}  {DIM}(t ~ n^k, 95% CI){X}")
    if fit.inconclusive:
        why = ("only %d usable measurement(s) above the noise floor" % len(fit.points)
               if len(fit.points) < 3 else
               ("no model fits the measurements (best R2=%.2f)" % fit.r2 if fit.r2 < 0.80
                else "exponent CI too wide to name a class"))
        print(f"  {Y}INCONCLUSIVE{X} — {why}; refusing to call it")
    else:
        verdict = G + "within budget" + X if ORDER_IDX(fit.best) <= ORDER_IDX(req) else R + f"needs O({req})" + X
        print(f"  measured {B}Θ({fit.best}){X}  R²={fit.r2:.3f}"
              f"   {DIM}(next: {fit.runner_up} R²={fit.runner_up_r2:.3f}){X}")
        print(f"  required Θ({req})  →  {verdict}")
        n_max, budget = p.meta["n_max"], p.meta["ops_budget"]
        from engine import MODELS
        ops = MODELS[fit.best](n_max)
        print(f"  {DIM}at n={n_max:,}: ~{ops:.2e} ops vs budget ~{budget:.2e}{X}")
    return 0


def ORDER_IDX(name):
    from engine import ORDER
    return ORDER.index(name) if name in ORDER else len(ORDER)


def main():
    ap = argparse.ArgumentParser(prog="cascade")
    sp = ap.add_subparsers(dest="cmd", required=True)

    g = sp.add_parser("gate", help="run the oracle validation gate")
    g.add_argument("problem"); g.add_argument("--trials", type=int, default=200)
    g.set_defaults(fn=cmd_gate)

    d = sp.add_parser("diagnose", help="run the cascade on a submission")
    d.add_argument("problem"); d.add_argument("submission")
    d.add_argument("--seeds", type=int, default=400)
    d.add_argument("--trials", type=int, default=5)
    d.add_argument("--student", default="student-1")
    d.set_defaults(fn=cmd_diagnose)

    a = ap.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
