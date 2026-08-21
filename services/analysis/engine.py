"""
Deterministic diagnosis engine — day 1 core.

Covers: execution harness, oracle validation gate, differential stress search,
typed shrinking (Test 42), and empirical complexity fitting.

NOT covered yet (by design): container isolation, memory caps on Windows,
LLM/firewall, AST mutation. See PROBLEM_CONTRACT.md and the spec.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

PY = sys.executable


# --------------------------------------------------------------------------
# 1. Execution harness
# --------------------------------------------------------------------------
@dataclass
class RunResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: Optional[int]
    ms: float
    timed_out: bool = False

    @property
    def out(self) -> str:
        return self.stdout.strip()


# --------------------------------------------------------------------------
# Isolation seam
#
# When a sandbox Session is installed, EVERY execution routes through it. The
# seam lives here, at the single choke point all student code already passes
# through, rather than at each of the dozen call sites — one place to get right,
# and impossible for a new call site to forget.
#
# Default is OFF, so the engine still runs on a machine with no Docker; the
# gateway turns it on, because that is where untrusted code actually arrives.
# --------------------------------------------------------------------------
# THREAD-LOCAL, not a module global. The gateway runs cascades concurrently in
# a worker pool; a single global session would mean one student's submission
# executing inside another student's container -- and, worse, being timed there.
# The same class of mistake as F24: correct in isolation, wrong under load.
_local = threading.local()


def set_sandbox(session) -> None:
    _local.session = session


def _sess():
    return getattr(_local, "session", None)


def sandbox_active() -> bool:
    return _sess() is not None


def _containerize(cmd: list[str]) -> list[str]:
    """Translate a host argv into the container's namespace.

    Two rewrites and a pass-through:
      * the host interpreter path -> plain `python`. The host's absolute
        sys.executable is meaningless inside the image, and on Windows it is a
        .exe that could never execute there at all.
      * any absolute path under the mounted workdir -> /work/<name>
      * anything already container-absolute (/work, /build) -> untouched
    """
    work = _sess().workdir
    out = []
    for a in cmd:
        if a == PY:
            out.append("python")
            continue
        try:
            p = pathlib.Path(a)
            if p.is_absolute() and work in p.resolve().parents:
                out.append("/work/" + p.resolve().relative_to(work).as_posix())
                continue
        except (OSError, ValueError):
            pass
        out.append(a)
    return out


def _touches_session(cmd: list[str]) -> bool:
    """Does this argv execute the SUBMISSION, as opposed to our own oracle?

    This is a security boundary, not an optimisation. The session mount must
    contain the submission and NOTHING ELSE, because whatever is mounted is
    readable by the code under test. Mounting the repository root -- which I did
    first, for convenience -- let a submission do this (BUILD_LOG F29):

        print(open('/work/problems/pair-sum-count/reference.py').read())

    and it worked: rc=0, reference solution on stdout. The same mount also
    exposed `.env` (the live API key), `knowledge.db`, and the whole corpus. An
    engine that proves defects with a mutation search is worth nothing if the
    answer key is readable from inside the box.

    So the submission runs isolated with only itself mounted, and the reference,
    brute force and generator -- OUR code, trusted by definition -- run on the
    host. They are not the threat, and putting them in the same container as the
    threat is precisely what created the leak.
    """
    work = _sess().workdir
    for a in cmd:
        if a.startswith("/work/") or a.startswith("/build/"):
            return True
        try:
            p = pathlib.Path(a)
            if p.is_absolute() and work in p.resolve().parents:
                return True
        except (OSError, ValueError):
            continue
    return False


def run(cmd: list[str], stdin: str = "", timeout_ms: int = 5000) -> RunResult:
    """Execute a process with a wall-clock kill. The caller owns the clock —
    never trust an in-process timer belonging to the code under test."""
    # `cmd[0] == "docker"` is the recursion guard: Session.exec calls back into
    # run() to get that wall clock, and must not be re-routed into itself.
    sess = _sess()
    if sess is not None and cmd and cmd[0] != "docker" and _touches_session(cmd):
        return sess.exec(_containerize(cmd), stdin, timeout_ms)
    t0 = time.perf_counter()
    try:
        p = subprocess.run(
            cmd, input=stdin, capture_output=True, text=True,
            timeout=timeout_ms / 1000.0,
        )
    except subprocess.TimeoutExpired:
        return RunResult(False, "", "timeout", None, timeout_ms, timed_out=True)
    ms = (time.perf_counter() - t0) * 1000.0
    return RunResult(p.returncode == 0, p.stdout, p.stderr, p.returncode, ms)


# --------------------------------------------------------------------------
# 1b. Language registry — compile once, execute many
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Language:
    name: str
    compile_cmd: Optional[list[str]]     # templates: {src} {out} {dir}
    run_cmd: list[str]


# -std=c++17, measured not guessed. Real submissions harvested from Codeforces
# were tagged C++17 and C++23. Compiling all 70 of them:
#   host GCC 6.3 -std=c++17   65/70  (std::gcd needs GCC 7+)
#   container    -std=c++17   70/70
#   container    -std=c++20   11/70  (bits/stdc++.h breaks under c++20 here)
# So c++17 in the container is the configuration that actually works.
LANGS: dict[str, Language] = {
    ".py":   Language("python", None, [PY, "{src}"]),
    ".cpp":  Language("cpp",  ["g++", "-O2", "-std=c++17", "-o", "{out}", "{src}"], ["{out}"]),
    ".cc":   Language("cpp",  ["g++", "-O2", "-std=c++17", "-o", "{out}", "{src}"], ["{out}"]),
}

# Java is deliberately ABSENT. It was in the original spec by convention -- the
# standard competitive-programming trio -- not by argument, and it is actively
# costly for THIS engine:
#
#   * JIT makes timing non-stationary. Early iterations run interpreted, later
#     ones compiled, so the runtime curve carries a compilation transition and is
#     not a clean power law. The complexity fitter would measure *when the JIT
#     kicked in* rather than the algorithm. Fixing that needs -Xint (10-50x
#     slower, so large n becomes unreachable) or a long warmup per data point.
#   * JVM startup (~50-100ms) is the F2 baseline-drowning problem, worse.
#   * `public class Main` must live in Main.java, so mutants cannot simply be
#     spliced to an arbitrary temp filename the way C++ mutants can.
#   * ~200MB of JDK in the runner image.
#
# Competitive programming is overwhelmingly C++ and Python. If Java returns it
# should return with the JIT problem solved first, as a deliberate decision.

_COMPILE_CACHE: dict[tuple[str, float], list[str]] = {}


class CompileError(RuntimeError):
    pass


def solution_cmd(path: str | pathlib.Path) -> list[str]:
    """Return an argv that executes this submission, compiling if the language
    needs it. Cached on (path, mtime) so a mutation search compiles each mutant
    exactly once rather than once per test case — the difference between a
    tractable and an intractable Bisect run on C++."""
    path = pathlib.Path(path)
    lang = LANGS.get(path.suffix.lower())
    if lang is None:
        raise CompileError(f"unsupported language: {path.suffix}")
    if lang.compile_cmd is None:
        return [c.replace("{src}", str(path)) for c in lang.run_cmd]

    # The cache key includes the isolation mode: a host build and a container
    # build are DIFFERENT BINARIES for the same source. On a Windows host they
    # are not even the same executable format, so serving one for the other
    # would fail in a way that looks like a broken submission.
    key = (str(path.resolve()), path.stat().st_mtime, sandbox_active())
    if key in _COMPILE_CACHE:
        return _COMPILE_CACHE[key]

    if _sess() is not None:
        # Compile INSIDE the container. /work is mounted read-only precisely so
        # the code under test cannot rewrite itself, so output goes to /build —
        # the one tmpfs that is writable and executable. /tmp stays noexec.
        src = "/work/" + path.resolve().relative_to(_sess().workdir).as_posix()
        outdir, out = "/build", f"/build/{path.stem}.out"
    else:
        outdir = str(pathlib.Path(tempfile.mkdtemp(prefix="dsabuild_")))
        out = str(pathlib.Path(outdir) / ("a.exe" if os.name == "nt" else "a.out"))
        src = str(path)
    cc = [c.format(src=src, out=out, dir=outdir) for c in lang.compile_cmd]
    r = run(cc, "", 60000)
    if not r.ok:
        raise CompileError(r.stderr.strip()[:400] or "compilation failed")
    cmd = [c.format(src=src, out=out, dir=outdir) for c in lang.run_cmd]
    _COMPILE_CACHE[key] = cmd
    return cmd


def language_available(ext: str) -> bool:
    lang = LANGS.get(ext.lower())
    if lang is None:
        return False
    if lang.compile_cmd is None:
        return True
    probe = run([lang.compile_cmd[0], "--version"], "", 10000)
    return probe.ok or "version" in (probe.stdout + probe.stderr).lower()


# --------------------------------------------------------------------------
# 2. Problem bundle
# --------------------------------------------------------------------------
@dataclass
class Problem:
    root: pathlib.Path
    meta: dict

    @classmethod
    def load(cls, path: str | pathlib.Path) -> "Problem":
        root = pathlib.Path(path)
        meta = json.loads((root / "problem.json").read_text(encoding="utf-8"))
        return cls(root, meta)

    def _cmd(self, stem: str) -> list[str]:
        """Resolve an oracle by STEM, not by filename.

        The oracle used to be hardcoded as `[PY, "reference.py"]`, which quietly
        made the whole harness Python-only. That is fine for problems I author
        and wrong for a corpus of real submissions: the R1 pairs harvested from
        Codeforces are 35/35 C++, so the accepted submission that serves as the
        oracle is a .cpp file. Routing through solution_cmd compiles it once and
        caches, exactly as it does for a student submission.
        """
        stem = stem[:-3] if stem.endswith(".py") else stem      # legacy callers
        for ext in (".py", ".cpp", ".cc"):
            f = self.root / (stem + ext)
            if f.exists():
                return solution_cmd(f)
        raise FileNotFoundError(f"no {stem}.(py|cpp|cc) in {self.root}")

    def reference(self, inp: str, timeout_ms=5000) -> RunResult:
        return run(self._cmd("reference"), inp, timeout_ms)

    def brute(self, inp: str, timeout_ms=10000) -> RunResult:
        return run(self._cmd("brute"), inp, timeout_ms)

    def validate(self, inp: str) -> RunResult:
        return run(self._cmd("validator"), inp, 5000)

    def generate(self, seed: int, n: int, adversarial=False) -> str:
        f = "generator_adv.py" if adversarial and (self.root / "generator_adv.py").exists() else "generator.py"
        r = run([PY, str(self.root / f), "--seed", str(seed), "--n", str(n)], timeout_ms=10000)
        if not r.ok:
            raise RuntimeError(f"generator failed: {r.stderr}")
        return r.stdout

    def samples(self) -> list[tuple[str, str]]:
        d = self.root / "samples"
        out = []
        for i in sorted(d.glob("*.in")):
            o = i.with_suffix(".out")
            if o.exists():
                out.append((i.read_text(encoding="utf-8"), o.read_text(encoding="utf-8").strip()))
        return out


# --------------------------------------------------------------------------
# 3. Oracle validation gate  (PROBLEM_CONTRACT.md §"Oracle validation gate")
# --------------------------------------------------------------------------
@dataclass
class GateReport:
    passed: bool
    checks: dict = field(default_factory=dict)
    detail: str = ""


def oracle_gate(p: Problem, trials: int = 200, small_n: int = 8) -> GateReport:
    """Four checks. Failure QUARANTINES THE PROBLEM — we never conclude a
    student is wrong when our own oracles disagree with each other."""
    checks, detail = {}, ""

    checks["reference_samples"] = all(p.reference(i).out == o for i, o in p.samples())
    checks["brute_samples"] = all(p.brute(i).out == o for i, o in p.samples())

    agree, valid = True, True
    for seed in range(trials):
        n = seed % small_n
        inp = p.generate(seed, n)
        if p.validate(inp).exit_code != 0:
            valid = False
            detail = f"validator rejected generated input at seed={seed} n={n}"
            break
        r, b = p.reference(inp), p.brute(inp)
        if r.out != b.out:
            agree = False
            detail = f"ORACLE DISAGREEMENT seed={seed} n={n}: ref={r.out!r} brute={b.out!r}"
            break
    checks["oracles_agree"] = agree
    checks["generator_valid"] = valid

    return GateReport(all(checks.values()), checks, detail)


# --------------------------------------------------------------------------
# 4. Differential stress search
# --------------------------------------------------------------------------
@dataclass
class Counterexample:
    input: str
    expected: str
    actual: str
    seed: int
    n: int
    original_size: int = 0
    shrink_steps: list[int] = field(default_factory=list)
    kind: str = "wrong_answer"          # wrong_answer | runtime_error


class InfrastructureError(RuntimeError):
    """OUR failure, not the student's. Must never become a diagnosis."""


# "Could not execute" as distinct from "executed and went wrong".
# 125/126/127 are the shell and OCI conventions for not-executable / not-found.
_INFRA_CODES = {125, 126, 127}
_INFRA_MARKERS = ("OCI runtime", "executable file not found",
                  "no such container", "permission denied")


def classify_run(r: RunResult) -> str:
    """Three outcomes, deliberately never collapsed into two.

    `stress` used to treat ANY output mismatch as a counterexample, including a
    program that never ran. When /build was mounted noexec, a perfectly correct
    C++ submission produced rc=126 and the engine reported a counterexample
    whose "actual output" was the string `<...permission denied>` (F34).

    That is the worst failure mode a tutor can have: not merely wrong, but
    confidently wrong, at scale, blaming the student for our broken toolchain --
    while a mutation search then hunts for a defect in code that has none.
    PROBLEM_CONTRACT already says an oracle disagreement quarantines the problem
    rather than blaming the student. The same rule must hold when the harness
    itself is what broke.
    """
    if r.ok:
        return "ok"
    blob = r.stderr or ""
    if r.exit_code in _INFRA_CODES or any(m in blob for m in _INFRA_MARKERS):
        return "infrastructure"
    return "runtime_error"          # crash, non-zero exit, timeout — student's


def stress(p: Problem, submission: pathlib.Path, max_seeds=400,
           n_schedule=(2, 3, 4, 5, 6, 8, 10, 14, 20)) -> Optional[Counterexample]:
    """Find the first input where the submission disagrees with the oracle.

    Raises InfrastructureError if the submission could not be executed at all: a
    broken harness must fail loudly here rather than quietly become a verdict
    about a student.
    """
    for seed in range(max_seeds):
        n = n_schedule[seed % len(n_schedule)]
        inp = p.generate(seed, n)
        exp = p.reference(inp).out
        got = run(solution_cmd(submission), inp, 5000)
        state = classify_run(got)
        if state == "infrastructure":
            raise InfrastructureError(
                f"could not execute the submission (rc={got.exit_code}): "
                f"{(got.stderr or '').strip()[:160]}")
        if state == "runtime_error":
            # A real defect, but NOT a wrong answer: there is no output to
            # compare, so a mutation search over expected-vs-actual is
            # meaningless. Report what actually happened instead.
            return Counterexample(inp, exp,
                                  f"<{(got.stderr or 'no output').strip()[:80]}>",
                                  seed, n, original_size=n, kind="runtime_error")
        if got.out != exp:
            return Counterexample(inp, exp, got.out, seed, n, original_size=n)
    return None


# --------------------------------------------------------------------------
# 5. Typed shrinker  (Test 42)
# --------------------------------------------------------------------------
def _parse_int_array(inp: str) -> tuple[int, int, list[int]]:
    d = inp.split()
    return int(d[0]), int(d[1]), [int(x) for x in d[2:]]


def _render_int_array(k: int, a: list[int]) -> str:
    return f"{len(a)} {k}\n" + " ".join(map(str, a)) + "\n"


def shrink_int_array(p: Problem, submission: pathlib.Path, ce: Counterexample) -> Counterexample:
    """ddmin over elements, then value reduction toward zero, then the header.

    INVARIANT on every candidate: still constraint-valid AND still failing.
    A candidate that breaks either is rejected and the search backtracks.
    """
    _, k, a = _parse_int_array(ce.input)
    steps = [len(a)]

    def fails(kk: int, arr: list[int]) -> Optional[tuple[str, str, str]]:
        inp = _render_int_array(kk, arr)
        if p.validate(inp).exit_code != 0:
            return None
        exp = p.reference(inp).out
        got = run(solution_cmd(submission), inp, 5000)
        actual = got.out if got.ok else f"<{got.stderr.strip()[:80]}>"
        return (inp, exp, actual) if actual != exp else None

    # --- phase 1: ddmin on elements -------------------------------------
    gran = 2
    while len(a) >= 2:
        chunk = max(1, len(a) // gran)
        reduced = False
        for i in range(0, len(a), chunk):
            cand = a[:i] + a[i + chunk:]
            if not cand:
                continue
            if fails(k, cand):
                a, gran, reduced = cand, max(gran - 1, 2), True
                steps.append(len(a))
                break
        if not reduced:
            if gran >= len(a):
                break
            gran = min(len(a), gran * 2)

    # --- phase 2: pull each value toward 0 ------------------------------
    for i in range(len(a)):
        while a[i] != 0:
            cand = list(a)
            cand[i] = cand[i] // 2 if abs(cand[i]) > 1 else 0
            if cand[i] == a[i] or not fails(k, cand):
                break
            a = cand

    # --- phase 3: shrink the target ------------------------------------
    while k != 0:
        cand_k = k // 2 if abs(k) > 1 else 0
        if cand_k == k or not fails(cand_k, a):
            break
        k = cand_k

    final = fails(k, a)
    if final is None:                      # never return an unverified shrink
        return ce
    inp, exp, actual = final
    return Counterexample(inp, exp, actual, ce.seed, len(a),
                          original_size=ce.original_size, shrink_steps=steps + [len(a)])


# --------------------------------------------------------------------------
# 6. Empirical complexity fitting
# --------------------------------------------------------------------------
MODELS = {
    "1":          lambda n: 1.0,
    "n":          lambda n: n,
    "n log n":    lambda n: n * math.log2(max(n, 2)),
    "n^2":        lambda n: n * n,
    "n^2 log n":  lambda n: n * n * math.log2(max(n, 2)),
    "n^3":        lambda n: n ** 3,
}

ORDER = ["1", "n", "n log n", "n^2", "n^2 log n", "n^3"]


@dataclass
class ComplexityFit:
    best: str
    r2: float
    runner_up: str
    runner_up_r2: float
    points: list[tuple[int, float]]
    inconclusive: bool
    cv: float
    exponent: float = 0.0        # log-log slope k in t ~ n^k
    exponent_se: float = 0.0     # standard error of k
    # Harness noise as a fraction of harness cost. A benchmark is only as good as
    # the machine under it, and "this machine is too busy to time on" is a
    # different -- and far more actionable -- answer than "the models cannot be
    # separated" (F43).
    noise_ratio: float = 0.0

    @property
    def ci95(self) -> float:
        return 1.96 * self.exponent_se

    def resolution(self) -> float:
        """Smallest exponent difference this measurement could possibly resolve.

        Over a measured range [n_lo, n_hi], `n` and `n log n` differ in effective
        exponent by only log(log n_hi / log n_lo) / log(n_hi / n_lo). For
        n = 25k..100k that is about 0.09. A confidence interval wider than the gap
        cannot tell those two models apart, no matter how good R2 looks.
        """
        ns = [n for n, _t in self.points]
        if len(ns) < 2:
            return float("inf")
        lo, hi = min(ns), max(ns)
        if lo < 2 or hi <= lo:
            return float("inf")
        return math.log(math.log(hi) / math.log(lo)) / math.log(hi / lo)

    def dominates(self, max_ci=0.35, min_r2=0.80) -> bool:
        """R2 saturates near 1.0 for every plausible model, so an R2 delta
        cannot discriminate n^2 from n^2 log n -- the exponent's confidence
        interval is the honest discriminator there. But a LOW R2 still means the
        measurements fit no model at all, and must never yield a verdict.

        THIRD GATE, added after a real user saw the wrong answer stated
        confidently (BUILD_LOG F42). Lowering the noise floor bought a third data
        point in the container and turned an honest INCONCLUSIVE into
        `Theta(n), k = 0.84 +/- 0.26` for a program the host measured as
        `Theta(n log n), k = 1.05 +/- 0.06`. Both gates above passed: the CI was
        inside 0.35 and R2 was high. What neither gate knew is that over the
        4x span of n that survived the floor, the exponent gap between n and
        n log n is 0.09 -- so a +/-0.26 interval could not separate them, and the
        verdict was arithmetic dressed as evidence.

        A fixed CI threshold is not a resolution claim. The interval has to be
        narrower than the gap it is being asked to resolve.
        """
        return (self.ci95 <= max_ci and self.r2 >= min_r2
                and self.ci95 <= max(self.resolution(), 0.05) * 2.0)


def _loglog_slope(ns: list[int], ts: list[float]) -> tuple[float, float]:
    """Slope of log(t) vs log(n) = the empirical exponent, with its std error."""
    xs = [math.log(n) for n in ns]
    ys = [math.log(t) for t in ts]
    m = len(xs)
    mx, my = sum(xs) / m, sum(ys) / m
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, float("inf")
    k = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    c = my - k * mx
    resid = [y - (k * x + c) for x, y in zip(xs, ys)]
    if m > 2:
        s2 = sum(r * r for r in resid) / (m - 2)
        se = math.sqrt(s2 / sxx)
    else:
        se = float("inf")
    return k, se


def _fit_one(ns, ts, f) -> float:
    """Least squares through the origin: t = c*f(n). Returns R²."""
    fs = [f(n) for n in ns]
    denom = sum(x * x for x in fs)
    if denom == 0:
        return -1.0
    c = sum(t * x for t, x in zip(ts, fs)) / denom
    mean = sum(ts) / len(ts)
    ss_res = sum((t - c * x) ** 2 for t, x in zip(ts, fs))
    ss_tot = sum((t - mean) ** 2 for t in ts)
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else -1.0


def judge(p: Problem, submission: pathlib.Path, trials: int = 3) -> dict:
    """What a contest judge would say: does it finish inside the limit at max n?

    This is the primary speed verdict, and it exists because the exponent fit was
    answering a question that cannot be answered on a developer laptop. Separating
    `n` from `n log n` needs an exponent resolved to ~0.09 over the range a laptop
    allows; three separate fixes (F30, F42, F44) failed to make that reliable,
    because the target was unattainable rather than the code wrong.

    A judge verdict has none of that fragility. "Finishes in 0.4 s against a 2 s
    limit" survives a 2x noise swing intact, needs no curve fitting, and is the
    thing a competitive programmer actually acts on.
    """
    n = int(p.meta.get("n_max", 200000))
    limit = int(p.meta.get("time_limit_ms", 2000))
    inp = p.generate(4242, n, adversarial=True)
    cmd = solution_cmd(submission)
    # Generous kill window, so we can report HOW slow rather than only "too slow".
    hard = max(limit * 5, 10000)
    best, timed_out = None, False
    for _ in range(trials):
        r = run(cmd, inp, hard)
        if r.timed_out:
            timed_out = True
            break
        best = r.ms if best is None else min(best, r.ms)
    return {"n": n, "limit_ms": limit, "ms": None if timed_out else best,
            "timed_out": timed_out,
            "ok": (not timed_out) and best is not None and best <= limit}


def reconcile(judge_result: dict, band: Optional[str]) -> Optional[str]:
    """Drop a growth band that contradicts the judge.

    Observed live: a quadratic submission that could NOT finish at n=200000 was
    labelled `sub-quadratic`, because the surviving fit points came from small n
    where container overhead flattens the curve (BUILD_LOG F46). Both claims came
    from the same run and cannot both be true.

    The judge is the robust one -- it is a single wall-clock measurement against a
    fixed limit, with no curve fitting to distort. So when they disagree, the band
    goes, not the verdict. Saying nothing is always available; saying two
    incompatible things is not.
    """
    if not band:
        return None
    too_slow = judge_result.get("timed_out") or not judge_result.get("ok")
    if too_slow and band == "sub-quadratic":
        return None
    if judge_result.get("ok") and band == "worse than quadratic":
        return None                 # comfortably inside the limit yet cubic: doubt it
    return band


def growth_band(fit: "ComplexityFit") -> Optional[str]:
    """A COARSE growth class, claimed only when the data can support it.

    Adjacent fine models (n vs n log n) differ by ~0.09 in exponent and are not
    separable here. Adjacent BANDS differ by a full 1.0, which survives ordinary
    noise -- so this reports the band and refuses the finer claim. The interval
    must sit entirely inside a band; if it straddles a boundary, say nothing.
    """
    if len(fit.points) < 3 or fit.r2 < 0.80:
        return None
    lo, hi = fit.exponent - fit.ci95, fit.exponent + fit.ci95
    if fit.ci95 > 0.5:
        return None
    if hi < 1.5:
        return "sub-quadratic"
    if lo > 1.5 and hi < 2.5:
        return "quadratic"
    if lo > 2.5:
        return "worse than quadratic"
    return None                     # interval straddles a band boundary


def _measure(p: Problem, submission: pathlib.Path, n: int, trials: int,
             timeout_ms: int, adversarial: bool,
             reps: int = 1) -> Optional[tuple[float, float]]:
    """Fastest observed wall-clock ms at size n, plus the coefficient of variation.

    `reps` times r consecutive runs as ONE observation. The caller uses that to
    lift a small-n point above the noise floor rather than discarding it: the
    returned value carries r baselines and r units of work, so the caller must
    subtract `base * reps` and divide by `reps` (see F43).
    """
    inp = p.generate(1234, n, adversarial=adversarial)
    cmd = solution_cmd(submission)          # compile once, not once per rep
    samples = []
    for t in range(trials + 1):
        total = 0.0
        for _ in range(reps):
            r = run(cmd, inp, timeout_ms)
            if r.timed_out:
                return None
            total += r.ms
        if t > 0:                           # discard first (warmup)
            samples.append(total)
    if not samples:
        return None
    samples.sort()
    # Minimum, not median: measurement noise is strictly one-sided (interference
    # only ever ADDS time), so the fastest observed run is the best estimator
    # of true cost. Standard benchmarking practice.
    med = samples[0]
    mean = sum(samples) / len(samples)
    sd = (sum((x - mean) ** 2 for x in samples) / len(samples)) ** 0.5
    return med, (sd / mean if mean else 0.0)


def _base_now(trials: int = 3) -> float:
    """The harness cost RIGHT NOW, sampled the same way a data point is.

    A single baseline taken before the sweep assumes the machine holds still for
    the ~60 s the sweep takes. It does not. A user's fit came back with
    n=3125 -> 54.9 ms and n=6250 -> 27.7 ms -- time going DOWN as n doubled --
    while the same program on the same host measured 8.8 and 14.2 ms minutes
    later. Nothing was wrong with the arithmetic; the load moved underneath it
    (BUILD_LOG F44).

    So the baseline is re-sampled at every point and drift is tracked instead of
    assumed away. Three no-op launches per point, about 150 ms -- irrelevant next
    to a wrong exponent.
    """
    sess = _sess()
    if sess is not None:
        return min(sess.exec(["python", "-c", "pass"], "", 10000).ms
                   for _ in range(trials))
    return min(run([PY, "-c", "pass"], "", 10000).ms for _ in range(trials))


def _baseline(trials: int = 3, groups: int = 7) -> tuple[float, float]:
    """Measure the harness itself: (median cost, jitter) of launching a no-op.

    The central value is the constant to subtract — without it a fast solution's
    signal is buried in process startup and every model fits equally badly (the
    failure that produced Theta(1), R2=0.000).

    The JITTER is the part that was missing, and it is what makes this instrument
    portable. `SIGNAL_FLOOR_MS = 12.0` was a constant tuned against host
    subprocess noise. Under container isolation the same code measured
    (BUILD_LOG F30):

        n=250 -> 28 ms, n=500 -> 19 ms          <- n doubled, time went DOWN

    Those two points are pure noise, and including them dragged a clean
    Theta(n^2) (k = 2.00 +/- 0.06) down to Theta(n log n) (k = 1.42 +/- 0.41).
    The fitter did not become wrong; the FLOOR became wrong, because the harness
    underneath it changed. So the floor is now derived from the noise actually
    measured rather than from a number that happened to fit one machine.

    CALIBRATE THE INSTRUMENT WHERE YOU MEASURE. The no-op probe must travel the
    same path as the submission. It does not go through `run()` for that: `run()`
    routes on whether the argv touches the session mount, and a bare `python -c
    pass` touches nothing, so it would silently be timed on the HOST while the
    submission is timed in the CONTAINER. Subtracting a 47 ms host baseline from
    a 172 ms container measurement leaves ~125 ms of pure overhead posing as
    work, which at small n is most of the reading -- measured as Theta(n),
    k = 0.89, for a quadratic solution (BUILD_LOG F31).

    MEASURE THE NOISE OF THE STATISTIC YOU ACTUALLY USE. This is F31's lesson one
    level deeper, and it took a real user hitting INCONCLUSIVE to expose it.
    `_measure` reports the MINIMUM of k runs, because interference only ever adds
    time. But the baseline reported the median of SINGLE runs and the floor came
    from the IQR of SINGLE runs -- and a single run is far noisier than a
    minimum-of-k. So the floor was defending against variance the measurement had
    already removed. Measured on a correct Theta(n log n) submission:

        host       floor 18 ms -> 4 usable points -> k = 1.17 +/- 0.03
        container  floor 80 ms -> 2 usable points -> INCONCLUSIVE

    Nothing was wrong with the container's timings; the 80 ms floor was computed
    from single-run spread and discarded every point below it, leaving fewer than
    the three a slope needs. So the baseline is now sampled exactly as a data
    point is -- minimum of `trials` runs -- repeated `groups` times, and the
    jitter is the IQR of those group minima.
    """
    sess = _sess()

    def once() -> float:
        if sess is not None:
            runs = [sess.exec(["python", "-c", "pass"], "", 10000).ms
                    for _ in range(trials)]
        else:
            runs = [run([PY, "-c", "pass"], "", 10000).ms for _ in range(trials)]
        return min(runs)                    # same estimator as _measure

    s = sorted(once() for _ in range(groups))
    med = s[len(s) // 2]
    # IQR, not max-min. The full spread is set by a SINGLE outlier, and one
    # scheduling hiccup then inflates the floor enough to discard good points:
    # measured, that turned a clean host fit into INCONCLUSIVE at random, which
    # is worse than a wrong answer because it is intermittent. Measured over 15
    # samples: host IQR 2.1 ms vs spread 4.7 ms; container IQR 22.1 vs spread
    # 62.2. At 4x, IQR gives host 12 ms -- identical to the constant that was
    # hand-tuned and verified over five sessions -- and container 88 ms, which
    # is what actually rejects the sub-noise points.
    jitter = s[3 * len(s) // 4] - s[len(s) // 4]
    return med, jitter


def fit_complexity(p: Problem, submission: pathlib.Path,
                   ns=None, trials=5, timeout_ms=30000, adversarial=True,
                   n_start=2000, points=6) -> ComplexityFit:
    """Measure, then select a model.

    Two corrections that make the instrument usable:
      1. Subtract measured interpreter startup — we fit the *work*, not the launch.
      2. Ramp n until the work dominates that baseline before collecting points,
         so the signal-to-noise ratio is high enough for model selection.
    All points run back to back so systematic noise is common-mode and largely
    cancels in the ratios we actually fit.
    """
    base, jitter = _baseline(trials=trials)
    noise_ratio = jitter / base if base else 0.0
    TIME_BUDGET_MS = 1500.0                # climb until work costs about this
    n_max = int(p.meta.get("n_max", 200000))

    # --- ramp UP to the time budget to maximise dynamic range ------------
    # Anchoring low and stepping up just clamps at n_max and yields one point;
    # anchoring high and stepping down gives a usable spread for the fit.
    n = max(64, n_start)
    while n < n_max:
        m = _measure(p, submission, n, 2, timeout_ms, adversarial)
        if m is None or (m[0] - base) >= TIME_BUDGET_MS:
            break
        nxt = min(n * 2, n_max)
        if nxt == n:
            break
        n = nxt

    # --- collect the fit points -----------------------------------------
    # Anchor at the largest measurable size and step DOWN by 4x. Stepping up
    # from a small n just clamps at n_max and yields a single point.
    # Derived from measured harness noise, not a fixed constant (F30).
    # 4x the observed spread: a point must clear the noise by a margin
    # before it is allowed to influence the slope.
    SIGNAL_FLOOR_MS = max(12.0, 4.0 * jitter)
    pts, cvs = [], []
    if ns is None:
        ns, cur = [], n
        for _ in range(points):
            if cur < 64:
                break
            ns.append(cur)
            cur //= 2
        ns = sorted(set(ns))
    # REPEAT SMALL POINTS INSTEAD OF DISCARDING THEM (BUILD_LOG F43).
    #
    # Dropping every point under the floor makes the fitter hostage to whatever
    # else the machine is doing. Measured on the same host minutes apart:
    #
    #     quiet   baseline  46 ms   IQR  2.3 ms   floor  12 ms  -> 4-5 points
    #     busy    baseline 114 ms   IQR 57.7 ms   floor 231 ms  -> 1 point
    #
    # Same program, same problem; a user hit the second case and got
    # "only 1 timing point". The floor is right to distrust a single fast run --
    # but the answer is to MEASURE IT HARDER, not to throw it away. Timing r
    # consecutive runs as one observation grows the signal by r while noise grows
    # by sqrt(r), so signal-to-noise improves by sqrt(r), and dividing back out
    # recovers the per-run cost. Standard practice for exactly this reason.
    MAX_REPS = 8
    for size in ns:
        reps, med, cv = 1, None, 0.0
        base_here = _base_now(trials)           # re-measured per point (F44)
        while True:
            m = _measure(p, submission, size, trials, timeout_ms, adversarial,
                         reps=reps)
            if m is None:
                break
            med, cv = m
            signal = med - base_here * reps     # r runs carry r baselines
            if signal >= SIGNAL_FLOOR_MS or reps >= MAX_REPS:
                break
            # how many repetitions would clear the floor, with headroom
            need = SIGNAL_FLOOR_MS / max(signal, 1e-6) * 1.5
            reps = min(MAX_REPS, max(reps * 2, int(reps * min(need, 4.0)) or reps * 2))
        if med is None:
            break
        signal = (med - base_here * reps) / reps  # back to per-run cost
        if signal * reps < SIGNAL_FLOOR_MS:     # still buried after MAX_REPS
            continue
        cvs.append(cv)
        pts.append((size, signal))

    if len(pts) < 3:
        return ComplexityFit("unknown", 0, "unknown", 0, pts, True,
                             sum(cvs) / len(cvs) if cvs else 0.0)

    nsx = [n for n, _ in pts]
    tsx = [t for _, t in pts]
    k, se = _loglog_slope(nsx, tsx)

    # Name the class by EFFECTIVE EXPONENT over the measured range, not by R2.
    # n^2 and n^2 log n both fit at R2=1.000; their effective exponents over the
    # same range differ by ~0.13, which is what actually separates them.
    lo, hi = min(nsx), max(nsx)
    span = math.log(hi / lo) if hi > lo else 1.0

    def effective(name: str) -> float:
        f = MODELS[name]
        return math.log(f(hi) / f(lo)) / span if f(lo) > 0 else 0.0

    scored = sorted(((name, _fit_one(nsx, tsx, MODELS[name])) for name in ORDER),
                    key=lambda kv: (abs(effective(kv[0]) - k), -kv[1]))
    (b, br), (r, rr) = scored[0], scored[1]
    cv = sum(cvs) / len(cvs)
    fit = ComplexityFit(b, br, r, rr, pts, False, cv, exponent=k, exponent_se=se)
    fit.noise_ratio = noise_ratio
    fit.inconclusive = not fit.dominates()
    return fit


def to_json(obj) -> str:
    return json.dumps(asdict(obj), indent=2, default=str)
