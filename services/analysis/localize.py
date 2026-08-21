"""Fault localization (Bisect) and the robustness gate (Forge).

Three confidence tiers, never conflated:
  PROVEN     - a single minimal mutation flips the whole suite fail->pass
  LOCALIZED  - spectrum-based fault localization (Ochiai) over line coverage
  STRUCTURAL - no local defect found; the approach itself is wrong

SBFL runs always because it is nearly free. Mutation search runs second and, when
it succeeds, UPGRADES the tier. Nothing else may perform that upgrade.
"""
from __future__ import annotations

import json
import math
import pathlib
import tempfile
from dataclasses import dataclass, field
from typing import Optional

import dispatch
from engine import PY, Problem, run, solution_cmd, CompileError

COVRUN = str(pathlib.Path(__file__).parent / "covrun.py")
SENTINEL = "__COV__"
SCHED = (2, 3, 4, 5, 6, 8, 10, 14, 20, 30)


@dataclass
class Case:
    inp: str
    expected: str


@dataclass
class Localization:
    tier: str                                   # PROVEN | LOCALIZED | STRUCTURAL
    lines: list[tuple[int, float]] = field(default_factory=list)   # (line, score)
    patch: Optional[str] = None                 # repair description, RESTRICTED
    patch_line: Optional[int] = None
    fault_sig: Optional[str] = None             # key into fault_signature -> concept
    tried: int = 0
    total_sites: int = 0
    overfit_rejected: int = 0       # repairs that passed the suite, failed holdout
    # FULL site identity: (start, end, replacement). Nothing shorter is unique.
    # Measured on one real line -- `prefix[0] = a[0]` -- the catalog emits FOUR
    # sites: two byte spans x two replacements. Two of them share the signature
    # `const:0->:-1`, and one is a real repair while the other is not. So neither
    # (line, sig) nor the span alone identifies a verdict.
    #
    # This is not cosmetic. Without it the engine's own conclusion cannot be
    # reproduced from its output, and an audit of F36 consequently applied the
    # WRONG site and reported a correct PROVEN as overfit -- inflating the
    # measured false-proven rate from 1/6 to 2/6 (BUILD_LOG F37).
    patch_site: Optional[tuple[int, int, str]] = None


# --------------------------------------------------------------------------
def coverage_of(script: pathlib.Path, inp: str, timeout_ms=8000) -> set[int]:
    r = run([PY, COVRUN, str(script)], inp, timeout_ms)
    for line in r.stderr.splitlines():
        if line.startswith(SENTINEL):
            try:
                return set(json.loads(line[len(SENTINEL):]))
            except Exception:
                return set()
    return set()


def build_suite(p: Problem, sub: pathlib.Path, max_seeds=200,
                want_fail=5, want_pass=8) -> tuple[list[Case], list[Case]]:
    """Collect failing and passing cases — SBFL needs both spectra."""
    fails: list[Case] = []
    passes: list[Case] = []
    for seed in range(max_seeds):
        n = SCHED[seed % len(SCHED)]
        inp = p.generate(seed, n)
        exp = p.reference(inp).out
        got = run(solution_cmd(sub), inp, 5000).out
        (fails if got != exp else passes).append(Case(inp, exp))
        if len(fails) >= want_fail and len(passes) >= want_pass:
            break
    return fails[:want_fail], passes[:want_pass]


def ochiai(sub: pathlib.Path, fails: list[Case], passes: list[Case]) -> list[tuple[int, float]]:
    """Suspiciousness per line: ef / sqrt(nf * (ef + ep)).

    Python only for now: the coverage wrapper uses sys.settrace. For C++
    this returns [] and the caller must treat that as "no pruning available",
    not as "nothing is suspicious".
    """
    if sub.suffix.lower() != ".py":
        return []
    n_lines = len(sub.read_text(encoding="utf-8").splitlines())
    cov_f = [coverage_of(sub, c.inp) for c in fails]
    cov_p = [coverage_of(sub, c.inp) for c in passes]
    nf = len(cov_f) or 1
    lines = set().union(*cov_f) if cov_f else set()
    scored = []
    for ln in sorted(lines):
        if not (1 <= ln <= n_lines):        # runpy emits synthetic frames
            continue
        ef = sum(1 for s in cov_f if ln in s)
        ep = sum(1 for s in cov_p if ln in s)
        denom = math.sqrt(nf * (ef + ep)) or 1.0
        scored.append((ln, ef / denom))
    scored.sort(key=lambda kv: (-kv[1], kv[0]))
    return scored


def has_discrimination(scores: list[tuple[int, float]], eps: float = 1e-9) -> bool:
    """SBFL only localizes when coverage actually DIFFERS between the failing
    and passing spectra. On a short straight-line program every line runs on
    every input, so every score ties — that is not a localization, and
    reporting it as one is exactly the false precision the tiers exist to
    prevent. When this returns False the verdict must degrade to STRUCTURAL.
    """
    if len(scores) < 2:
        return False
    vals = [s for _, s in scores]
    return (max(vals) - min(vals)) > eps


def _passes_all(script: pathlib.Path, cases: list[Case], timeout_ms=6000) -> bool:
    """A mutant that does not compile is a DEAD mutant, not an error. Letting
    CompileError escape aborts the whole search on the first syntactically
    invalid splice, which on C++ is guaranteed to happen early (BUILD_LOG F19)."""
    try:
        cmd = solution_cmd(script)
    except CompileError:
        return False
    for c in cases:
        r = run(cmd, c.inp, timeout_ms)
        if not r.ok or r.out != c.expected:
            return False
    return True


def repair_search(p: Problem, sub: pathlib.Path, fails: list[Case], passes: list[Case],
                  scores: list[tuple[int, float]], budget=400) -> Localization:
    """Find a single mutation of the student's code that flips the whole suite.

    Coverage-guided pruning: a mutation on a line no failing test executes cannot
    change the failing outcome. That is a soundness argument, not a heuristic,
    and it removes most candidate sites on a real submission.
    """
    src = sub.read_text(encoding="utf-8")
    sites = dispatch.sites_for(sub, src)
    suspicious = {ln: s for ln, s in scores}
    covered = set(suspicious)

    # Coverage-guided pruning is SOUND only while coverage exists. When it does
    # not -- C++ has no settrace equivalent here -- an empty covered set
    # prunes every candidate and the search silently returns STRUCTURAL for
    # every submission (BUILD_LOG F18). Pruning is an optimisation; with no data
    # it must degrade to a no-op, never to a total filter.
    if covered:
        candidates = [s for s in sites if s.line in covered]
    else:
        candidates = list(sites)
    candidates.sort(key=lambda s: -suspicious.get(s.line, 0.0))

    all_cases = fails + passes
    tried = 0
    overfit = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td) / ("mutant" + sub.suffix)
        for site in candidates[:budget]:
            m = dispatch.apply_for(sub, src, site)
            if m is None:
                continue
            tried += 1
            tmp.write_text(m, encoding="utf-8")
            if not _passes_all(tmp, all_cases):
                continue
            # HOLDOUT CONFIRMATION — see confirm_repair. Passing the suite is not
            # proof: the suite is 13 sampled cases and it is the SAME evidence
            # the search used to pick this site.
            if not confirm_repair(p, tmp):
                overfit += 1
                continue
            return Localization("PROVEN", scores, site.label, site.line,
                                site.sig, tried, len(sites),
                                patch_site=(site.start, site.end, site.repl))
    # No single mutation repairs it. Fall back to the coverage spectrum — but
    # only claim LOCALIZED if the spectrum can actually discriminate.
    tier = "LOCALIZED" if has_discrimination(scores) else "STRUCTURAL"
    return Localization(tier, scores, None, None, None, tried, len(sites),
                        overfit_rejected=overfit)


CONFIRM_SEEDS = 100
CONFIRM_OFFSET = 100_000          # disjoint from build_suite's range(200)
CONFIRM_SCHED = (2, 3, 5, 8, 12, 20, 35, 60, 100, 160)


def confirm_repair(p: Problem, mutant: pathlib.Path,
                   n_seeds: int = CONFIRM_SEEDS) -> bool:
    """Independent confirmation that a candidate repair actually repairs.

    WHY THIS EXISTS. `repair_search` used to return PROVEN the moment a mutation
    passed `fails + passes` -- 13 sampled cases, and the very same cases the
    spectrum used to rank the site. That is validating a hypothesis on its
    training data, and R1 measured the cost: of 6 audited PROVEN verdicts whose
    line disagreed with the true edit, 2 were repairs that satisfied the suite
    and then FAILED at 200 fresh seeds. The engine had said "proven" about a
    change that does not fix the program (BUILD_LOG F36).

    All 6 audited repairs were `const` mutations. Constants are the largest and
    least constrained region of the operator space, so they are the most likely
    to satisfy a small suite by coincidence -- which is exactly why a claim this
    strong needs evidence the search has not already seen.

    TWO SWEEPS, and the first one matters more than it looks.

    My first attempt sampled only high seeds (offset 100_000) on the theory that
    confirmation must not reuse the suite's inputs. It missed a repair the audit
    had already PROVEN to be overfit. The reason is that `build_suite` BREAKS
    EARLY -- as soon as it holds 5 failures and 8 passes, often within ~15 seeds
    -- so the low seed range is barely sampled, not exhausted. The failure was
    sitting at a low seed the suite never reached, and a distant region of the
    seed space could not see it.

    So confirmation sweeps DENSELY from seed 0 (strictly more than the suite
    covered, and exactly the check that caught the defect), and then again at
    much larger n, because an off-by-one at a boundary is often invisible at n=3
    and obvious at n=160.
    """
    for seed in range(n_seeds):                       # dense, from zero
        n = SCHED[seed % len(SCHED)]
        inp = p.generate(seed, n)
        if run(solution_cmd(mutant), inp, 8000).out != p.reference(inp).out:
            return False
    for i in range(len(CONFIRM_SCHED) * 3):           # and at scale
        seed = CONFIRM_OFFSET + i
        n = CONFIRM_SCHED[i % len(CONFIRM_SCHED)]
        inp = p.generate(seed, n)
        if run(solution_cmd(mutant), inp, 8000).out != p.reference(inp).out:
            return False
    return True


def localize(p: Problem, sub: pathlib.Path, budget=400) -> tuple[Localization, list[Case], list[Case]]:
    fails, passes = build_suite(p, sub)
    if not fails:
        return Localization("STRUCTURAL", [], None, None, None, 0, 0), fails, passes
    scores = ochiai(sub, fails, passes)
    return repair_search(p, sub, fails, passes, scores, budget), fails, passes


# --------------------------------------------------------------------------
# Forge — the robustness gate
# --------------------------------------------------------------------------
@dataclass
class ForgeReport:
    total: int
    killed: int
    survived: list[str]
    latent_bug: Optional[dict] = None

    @property
    def score(self) -> float:
        return self.killed / self.total if self.total else 0.0


def forge(p: Problem, sub: pathlib.Path, suite: list[Case], budget=60,
          hunt_seeds=120) -> ForgeReport:
    """Mutate an ACCEPTED solution. A mutant that survives the suite means the
    tested behaviour is under-specified. We then hunt an input that kills the
    mutant and re-run the ORIGINAL on it: if the original also fails, the
    student had a latent bug the judge never exercised.
    """
    src = sub.read_text(encoding="utf-8")
    sites = dispatch.sites_for(sub, src)[:budget]
    survived: list[str] = []
    killed = 0
    latent = None

    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td) / ("mutant" + sub.suffix)
        for site in sites:
            m = dispatch.apply_for(sub, src, site)
            if m is None:
                continue
            tmp.write_text(m, encoding="utf-8")
            if _passes_all(tmp, suite):
                survived.append(site.label)
                if latent is None:
                    latent = _hunt_latent(p, sub, tmp, hunt_seeds)
            else:
                killed += 1

    total = killed + len(survived)
    return ForgeReport(total, killed, survived, latent)


def _hunt_latent(p: Problem, original: pathlib.Path, mutant: pathlib.Path,
                 seeds: int) -> Optional[dict]:
    """Find an input separating mutant from original, then test the original
    against the oracle on it."""
    for seed in range(1000, 1000 + seeds):
        n = SCHED[seed % len(SCHED)]
        inp = p.generate(seed, n)
        o = run(solution_cmd(original), inp, 5000).out
        m = run(solution_cmd(mutant), inp, 5000).out
        if o == m:
            continue
        exp = p.reference(inp).out
        if o != exp:
            return {"input": inp.strip(), "expected": exp, "actual": o}
    return None
