"""Turn real Codeforces WA->AC pairs into runnable problem bundles.

This is the R1 corpus the experiment actually wanted: bugs written by a human
under contest pressure, and the human's own accepted fix as ground truth.

THE ORACLE IS THE STUDENT'S OWN ACCEPTED SUBMISSION. That is the trick that makes
this work without problem statements, which Codeforces does not expose. We do not
need to know what the problem *means* -- we need a correct program to disagree
with, and Codeforces' own judge already certified one. The buggy version and the
accepted version differ; wherever they disagree on a valid input, that is a real
defect with a known location (the diff).

WHAT IS STILL SYNTHETIC, AND WHY IT IS THE WEAK POINT. The input GENERATOR has to
be inferred, because the statement (and therefore the constraints) is unavailable.
A generator that emits out-of-constraint input can make two programs disagree for
reasons that are nobody's bug -- so a disagreement is only admitted when:

  * the ACCEPTED program runs cleanly (rc=0) on the input, and
  * the accepted program's output is non-empty, and
  * the disagreement reproduces across several independent seeds.

An accepted solution crashing or timing out is treated as evidence that the
GENERATOR is wrong, never as evidence about the submission. Pairs that cannot
clear that bar are dropped and counted, not quietly kept.

Input:  corpus_r1/cf_sources.json   (from scripts/cf_fetch.js)
Output: problems_cf/<contest><index>/  + corpus_r1/cf_manifest.json
"""
import difflib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "analysis"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import engine as ENG
import llm as L
import sandbox as SBX
from engine import Problem, run, solution_cmd

SRC = ROOT / "corpus_r1" / "cf_sources.json"
OUT = ROOT / "problems_cf"
CORPUS = ROOT / "corpus_r1" / "cf"

SYS_GEN = """You write input GENERATORS for competitive-programming problems.

You are given an ACCEPTED C++ solution. Infer the input format it reads and write
a Python 3 generator that emits VALID random input for it.

Rules:
- argparse with exactly --seed and --n. Seed random with the seed for determinism.
- Use --n as the primary size knob (array length, number of queries, etc).
- If the program reads a testcase count t first, emit t=1 unless it clearly needs more.
- Keep VALUES SMALL (magnitudes under 50) so brute-force disagreement is likely,
  but respect any constraint you can infer from the code (non-negative, sorted,
  distinct, sum limits, 0/1 only, etc).
- Output ONLY the program. No markdown fences, no comments, no explanation."""

PROBLEM_JSON = {
    "n_max": 2000, "time_limit_ms": 2000, "ops_budget": 400000000,
    "required_complexity": "n", "solution_family": ["unknown"],
    "concepts": [], "edge_cases": [],
    "shrink_hint": {"kind": "int_array", "header_lines": 1},
}


def strip_fences(t: str) -> str:
    t = re.sub(r"^\s*```[a-zA-Z]*\s*", "", t.strip())
    return re.sub(r"```\s*$", "", t.strip()).strip() + "\n"


def changed_lines(a: str, b: str) -> list[int]:
    la, lb = a.splitlines(), b.splitlines()
    out = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(a=la, b=lb).get_opcodes():
        if tag in ("replace", "insert"):
            out.extend(range(j1 + 1, j2 + 1))
    return out


def main() -> int:
    if not SRC.exists():
        print(f"  missing {SRC.relative_to(ROOT)}")
        print("  run scripts/cf_fetch.js in a logged-in codeforces.com console first.")
        return 2
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    got = {(r["cid"], r["idx"], r["role"]): r for r in rows if r.get("ok") and r.get("source")}
    keys = sorted({(c, i) for (c, i, _r) in got})
    print(f"  {len(rows)} fetched, {len(got)} with source, {len(keys)} problems\n")

    OUT.mkdir(exist_ok=True)
    CORPUS.mkdir(parents=True, exist_ok=True)
    gen = L.GeminiClient(L.LLMConfig(provider="gemini", allow_network=True, model="",
                                     max_output_tokens=1100, temperature=0.4))
    MF = ROOT / "corpus_r1" / "cf_manifest.json"
    prev = json.loads(MF.read_text(encoding="utf-8")) if MF.exists() else []
    DROP = ROOT / "corpus_r1" / "cf_dropped.json"
    dropped = json.loads(DROP.read_text(encoding="utf-8")) if DROP.exists() else {}
    kept = list(prev)
    seen = {r["slug"] for r in prev} | set(dropped)
    print(f"  resuming: {len(prev)} kept, {len(dropped)} dropped already\n")

    for cid, idx in keys:
        slug = f"{cid}{idx}"
        if slug in seen:
            continue
        buggy = got.get((cid, idx, "buggy"))
        fixed = got.get((cid, idx, "fixed"))
        if not buggy or not fixed:
            dropped[slug] = "missing one side"
            continue

        d = OUT / slug
        d.mkdir(exist_ok=True)
        (d / "reference.cpp").write_text(fixed["source"], encoding="utf-8")
        (d / "brute.cpp").write_text(fixed["source"], encoding="utf-8")
        meta = dict(PROBLEM_JSON, slug=slug, title=f"Codeforces {slug}",
                    statement="(statement unavailable; oracle is the accepted submission)")
        (d / "problem.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        (d / "validator.py").write_text("import sys\nsys.stdin.read()\nsys.exit(0)\n",
                                        encoding="utf-8")
        # The buggy submission lives INSIDE the bundle dir so ONE container
        # mount covers oracle, generator and submission. Compilation must happen
        # in the container: the host g++ is GCC 6.3 and fails 5/70 of these.
        #
        # This deliberately differs from the student-facing rule in F29 (mount
        # the submission and nothing else). That rule exists to stop a LIVE
        # student reading the answer key. Here there is no student: this is a
        # batch evaluation over archived submissions where both sides are ours
        # and already known. The distinction is stated rather than blurred.
        bpath = d / "sub.cpp"
        bpath.write_text(buggy["source"], encoding="utf-8")

        sess = None
        try:
            g = strip_fences(gen.complete(SYS_GEN,
                f"Accepted solution for Codeforces {slug}:\n\n{fixed['source'][:6000]}"))
            (d / "generator.py").write_text(g, encoding="utf-8")
            p = Problem.load(d)
            sess = SBX.Session(d).start()
            ENG.set_sandbox(sess)

            # 1. the generator must produce input the ACCEPTED program accepts.
            #    Failure here indicts the generator, never the submission.
            ok_ref = 0
            for seed in range(6):
                inp = p.generate(seed, 8)
                r = p.reference(inp)
                if r.ok and r.out:
                    ok_ref += 1
            if ok_ref < 5:
                dropped[slug] = f"generator rejected by accepted solution ({ok_ref}/6)"
                continue

            # 2. a real disagreement, reproduced on more than one seed
            wit, hits = None, 0
            for seed in range(60):
                inp = p.generate(seed, 8 + (seed % 12))
                ref = p.reference(inp)
                if not (ref.ok and ref.out):
                    continue
                sub = run(solution_cmd(bpath), inp, 6000)
                if sub.ok and sub.out != ref.out:
                    hits += 1
                    wit = wit or {"input": inp.strip()[:160], "expected": ref.out,
                                  "actual": sub.out[:60]}
            if hits < 2:
                dropped[slug] = f"no reproducible disagreement (hits={hits})"
                continue

            lines = changed_lines(fixed["source"], buggy["source"])
            kept.append({"slug": slug, "problem": str(d.relative_to(ROOT)).replace("\\", "/"),
                         "buggy": str(bpath.relative_to(ROOT)).replace("\\", "/"),
                         "lang": buggy.get("lang", "cpp"), "verdict": "real-human-bug",
                         "true_lines": lines, "disagreements": hits, "witness": wit})
            print(f"  KEEP {slug:<9} diff={len(lines):<3} lines {lines[:5]}  disagreements {hits}/60")
            MF.write_text(json.dumps(kept, indent=2), encoding="utf-8")
        except Exception as e:
            dropped[slug] = f"{type(e).__name__}: {str(e)[:60]}"
        finally:
            DROP.write_text(json.dumps(dropped, indent=2), encoding="utf-8")
            ENG.set_sandbox(None)
            if sess is not None:
                sess.close()

    MF.write_text(json.dumps(kept, indent=2), encoding="utf-8")
    DROP.write_text(json.dumps(dropped, indent=2), encoding="utf-8")
    print(f"\n  REAL HUMAN PAIRS USABLE: {len(kept)} / {len(keys)}")
    if dropped:
        print("  dropped (counted, not hidden):")
        for k, v in list(dropped.items())[:20]:
            print(f"    {k:<10} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
