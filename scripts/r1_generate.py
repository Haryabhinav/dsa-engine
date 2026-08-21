"""R1 corpus: real (correct, buggy) program pairs from an INDEPENDENT bug source.

WHY NOT HARVESTED FROM CODEFORCES. Checked, empirically, not assumed: the
Codeforces API exposes problem metadata and submission *verdicts* but no source
code and no statements, and the public submission pages sit behind a Cloudflare
bot check which is not something to work around. LeetCode submissions are
private. So real human submission source is not obtainable here, and this file
says so rather than pretending otherwise.

THE TRAP THIS IS DESIGNED AROUND. R1 asks whether the mutation search finds real
bugs. The existing corpus cannot answer it, because I wrote those bugs, so they
are bugs I can imagine. But the obvious replacement is worse: generating bugs
from the same operator catalog `mutate.py` searches makes the hit rate ~100% BY
CONSTRUCTION and the number meaningless.

So bugs come from a source independent of the repair search -- a model that has
never seen the catalog -- and are described in HUMAN error categories (off-by-one
at a boundary, wrong initial sentinel, unhandled empty input, wrong update
order), not in mutation operators.

Some of those will coincidentally land inside the catalog and some will not, and
that is the interesting part: the evaluation reports hit rate SEPARATELY for
in-catalog and out-of-catalog bugs. A single blended number would hide exactly
the thing worth knowing.

LABELS COME FROM EXECUTION, NEVER FROM THE MODEL. A "correct" program is kept
only if differential stress finds no disagreement with the reference; a "buggy"
one only if stress does find one. The model's claim about its own output is
treated as a hypothesis.

Run:  python scripts/r1_generate.py [n_per_problem]
"""
import concurrent.futures as cf
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

import llm as L
from engine import Problem, stress

OUT = ROOT / "corpus_r1"

# HUMAN error categories, deliberately not mutation operators. Two of these
# (boundary, comparison direction) will often land inside the catalog; the rest
# usually will not. That split is the measurement.
BUG_KINDS = [
    "an off-by-one error at a loop or index boundary",
    "the wrong initial value for an accumulator or sentinel",
    "a missing guard for an empty or single-element input",
    "two statements in the wrong order, so a variable is read before it is updated",
    "the wrong variable used in one place (a plausible name confusion)",
    "an inclusive/exclusive mistake in a slice or range",
    "a condition that handles duplicates or ties incorrectly",
    "an early return or break that fires one iteration too soon",
]

SYS_SOLVE = """You write short competitive-programming solutions in Python 3.

Rules:
- Read ALL input from stdin, write ONLY the answer to stdout.
- Input format is: a first line "n k", then n integers (whitespace separated).
- No comments, no explanation, no markdown fences. Output ONLY the program.
- The program must be self-contained and must define and call main()."""

SYS_BREAK = """You introduce a single realistic bug into a working Python program.

Rules:
- Change as little as possible: ideally ONE line, at most two.
- The program must still parse and still run without crashing on typical input.
- Do NOT add comments marking the bug. Do NOT explain. Do NOT use markdown fences.
- Output ONLY the modified program."""


def strip_fences(t: str) -> str:
    t = re.sub(r"^\s*```[a-zA-Z]*\s*", "", t.strip())
    t = re.sub(r"```\s*$", "", t.strip())
    return t.strip() + "\n"


def changed_lines(correct: str, buggy: str) -> list[int]:
    """1-indexed lines of `buggy` that differ from `correct` — the ground-truth
    bug location the localizer is scored against."""
    a, b = correct.splitlines(), buggy.splitlines()
    out = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b).get_opcodes():
        if tag in ("replace", "insert"):
            out.extend(range(j1 + 1, j2 + 1))
    return out


def one(problem_dir: pathlib.Path, idx: int) -> dict | None:
    p = Problem.load(problem_dir)
    slug = p.meta["slug"]
    kind = BUG_KINDS[idx % len(BUG_KINDS)]
    gen = L.GeminiClient(L.LLMConfig(provider="gemini", allow_network=True, model="",
                                     max_output_tokens=1200, temperature=0.85))
    d = OUT / slug
    d.mkdir(parents=True, exist_ok=True)

    try:
        prompt = (f"Problem: {p.meta['title']}\n{p.meta['statement']}\n\n"
                  f"Write a correct, efficient Python 3 solution. Aim for "
                  f"O({p.meta['required_complexity']}) time.")
        correct = strip_fences(gen.complete(SYS_SOLVE, prompt))
        cpath = d / f"{idx:02d}_correct.py"
        cpath.write_text(correct, encoding="utf-8")

        # LABEL BY EXECUTION: is the model's "correct" program actually correct?
        if stress(p, cpath, max_seeds=40) is not None:
            cpath.unlink(missing_ok=True)
            return {"slug": slug, "idx": idx, "status": "model_solution_wrong"}

        buggy = strip_fences(gen.complete(
            SYS_BREAK,
            f"Introduce {kind} into this program.\n\n{correct}"))
        bpath = d / f"{idx:02d}_buggy.py"
        bpath.write_text(buggy, encoding="utf-8")

        lines = changed_lines(correct, buggy)
        if not lines:
            bpath.unlink(missing_ok=True)
            return {"slug": slug, "idx": idx, "status": "no_change"}

        ce = stress(p, bpath, max_seeds=60)
        if ce is None:
            bpath.unlink(missing_ok=True)
            return {"slug": slug, "idx": idx, "status": "bug_not_observable"}

        return {"slug": slug, "idx": idx, "status": "ok", "bug_kind": kind,
                "correct": str(cpath.relative_to(ROOT)).replace("\\", "/"),
                "buggy": str(bpath.relative_to(ROOT)).replace("\\", "/"),
                "true_lines": lines,
                "witness": {"input": ce.input.strip()[:120],
                            "expected": ce.expected, "actual": ce.actual[:40]}}
    except Exception as e:
        return {"slug": slug, "idx": idx, "status": f"error:{type(e).__name__}",
                "detail": str(e)[:120]}


def main() -> int:
    per = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    off = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    dirs = sorted(d for d in (ROOT / "problems").iterdir() if d.is_dir())
    jobs = [(d, i) for d in dirs for i in range(off, off + per)]
    print(f"  {len(dirs)} problems x {per} attempts = {len(jobs)} candidate pairs\n")

    results = []
    with cf.ThreadPoolExecutor(max_workers=5) as pool:
        futs = {pool.submit(one, d, i): (d, i) for d, i in jobs}
        for n, f in enumerate(cf.as_completed(futs), 1):
            r = f.result()
            results.append(r)
            if r and r["status"] == "ok":
                print(f"  [{n:3d}/{len(jobs)}] KEEP {r['slug']:<24} lines={r['true_lines']}")
            elif n % 10 == 0:
                print(f"  [{n:3d}/{len(jobs)}] …")

    kept = [r for r in results if r and r["status"] == "ok"]
    # MERGE, so the corpus can be built in chunks without losing earlier work
    mf = OUT / "manifest.json"
    if mf.exists():
        prev = json.loads(mf.read_text(encoding="utf-8"))
        seen = {(r["slug"], r["idx"]) for r in kept}
        kept = kept + [r for r in prev if (r["slug"], r["idx"]) not in seen]
    mf.write_text(json.dumps(kept, indent=2), encoding="utf-8")

    from collections import Counter
    why = Counter(r["status"] for r in results if r)
    print(f"\n  VALIDATED PAIRS: {len(kept)}")
    print("  rejected, by reason (labels come from execution, not the model):")
    for k, v in why.most_common():
        if k != "ok":
            print(f"    {v:3d}  {k}")
    per_problem = Counter(r["slug"] for r in kept)
    print("\n  per problem:")
    for slug, c in sorted(per_problem.items()):
        print(f"    {c:3d}  {slug}")
    print(f"\n  manifest -> {(OUT / 'manifest.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
