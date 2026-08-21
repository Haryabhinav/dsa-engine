"""Verify the sandbox is WIRED IN, not merely present.

`python -m sandbox selftest` proves the container controls work. It does not
prove the engine uses them. Between those two facts sat five sessions in which
sandbox.py existed and every submission still ran as a bare host subprocess --
the module was written, imported by nothing, and I reported the isolation as
built.

So this script tests the seam, not the sandbox:

  1. AGREEMENT   -- the same submission must reach the same verdict isolated as
                    it does on the host. Isolation that changes the answer is a
                    bug, not a feature.
  2. MEASUREMENT -- the complexity fitter must survive the container. This is
                    the one that nearly broke: per-exec `docker run` adds 317 ms
                    of jitter against a 12 ms signal floor.
  3. CONTAINMENT -- hostile submissions must be stopped BY THE ENGINE'S OWN
                    PATH, not by a hand-written docker command in a test.

Run:  python scripts/verify_sandbox_wiring.py
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "analysis"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import engine as E
import sandbox as S
from engine import Problem, fit_complexity, run, solution_cmd, stress

PROBLEM = ROOT / "problems" / "pair-sum-count"
SUB = ROOT / "corpus" / "wrong_selfpair.py"
QUAD = ROOT / "corpus" / "correct_quadratic.py"
SCRATCH = ROOT / ".scratch"
# The mount is the blast radius. It holds the submission and nothing else --
# no problems/, no corpus/, no knowledge.db, no .env (F29).
BOX = SCRATCH / "box"

HOSTILE = {
    "exfiltrate": "import socket\nsocket.create_connection(('1.1.1.1',53),3)\nprint('LEAKED')\n",
    "fork bomb": "import os\nwhile True: os.fork()\n",
    "memory bomb": "b=[]\nwhile True: b.append(' '*10**7)\n",
    "write to disk": "open('/work/pwned','w').write('x')\nprint('WROTE')\n",
    "read the answers": "print(open('/work/problems/pair-sum-count/reference.py').read())\n",
    "steal the api key": "print('KEY=' + open('/work/.env').read())\n",
    "list the mount": "import os\nprint('MOUNT=' + ','.join(sorted(os.listdir('/work'))))\n",
}


def banner(t):
    print("\n" + "=" * 70)
    print(t)
    print("=" * 70)


def diagnose(p, sub):
    ce = stress(p, sub, max_seeds=30)
    return None if ce is None else (ce.input.strip(), ce.expected, ce.actual)


def main() -> int:
    if not S.available():
        print("docker daemon not reachable — cannot verify the wiring.")
        return 2
    SCRATCH.mkdir(exist_ok=True)
    import shutil
    shutil.rmtree(BOX, ignore_errors=True)
    BOX.mkdir(parents=True)
    sub = BOX / "sub.py"; sub.write_text(SUB.read_text(encoding="utf-8"), encoding="utf-8")
    quad = BOX / "quad.py"; quad.write_text(QUAD.read_text(encoding="utf-8"), encoding="utf-8")
    p = Problem.load(PROBLEM)
    fails = 0

    banner("1. AGREEMENT — host vs isolated must reach the SAME verdict")
    host_ce = diagnose(p, sub)
    host_fit = fit_complexity(p, quad, trials=3)
    print(f"  host     counterexample : {host_ce}")
    print(f"  host     complexity     : Theta({host_fit.best})  k={host_fit.exponent:.2f}±{host_fit.ci95:.2f}")

    with S.Session(BOX) as sess:
        E.set_sandbox(sess)
        try:
            print(f"  container: {sess.name}")
            box_ce = diagnose(p, sub)
            print(f"  isolated counterexample : {box_ce}")
            if box_ce != host_ce:
                print("  ! MISMATCH — isolation changed the diagnosis")
                fails += 1

            banner("2. MEASUREMENT — does the fitter survive the container?")
            box_fit = fit_complexity(p, quad, trials=3)
            print(f"  isolated complexity     : Theta({box_fit.best})  "
                  f"k={box_fit.exponent:.2f}±{box_fit.ci95:.2f}  r2={box_fit.r2:.3f}")
            print(f"  points: {[(n, round(t)) for n, t in box_fit.points]}")
            # Compare the MEASUREMENT, not its label. `best` is a discretisation
            # of k, so a fit at k=2.04 can legitimately be named n^2 on one run
            # and n^2 log n on another while the underlying measurement is the
            # same. Agreement means the exponents overlap within their intervals.
            tol = host_fit.ci95 + box_fit.ci95 + 0.15
            if abs(box_fit.exponent - host_fit.exponent) > tol:
                print(f"  ! MISMATCH — host k={host_fit.exponent:.2f}, "
                      f"container k={box_fit.exponent:.2f} (tolerance {tol:.2f})")
                fails += 1
            elif box_fit.best != host_fit.best:
                print(f"  note: same measurement, different label "
                      f"({host_fit.best} vs {box_fit.best}) — k agrees within {tol:.2f}")
            if box_fit.inconclusive:
                print("  ! fitter went INCONCLUSIVE under isolation")
                fails += 1

            banner("3. CONTAINMENT — through the engine's own execution path")
            for name, src in HOSTILE.items():
                f = BOX / f"hostile_{name.replace(' ', '_')}.py"
                f.write_text(src, encoding="utf-8")
                r = run(solution_cmd(f), "", 8000)
                out = (r.stdout + r.stderr).strip().replace("\n", " ")[:60]
                # containment == the program did not achieve its goal
                escaped = r.ok and any(m in r.stdout for m in
                                       ("LEAKED", "WROTE", "def main", "KEY=", "GEMINI"))
                if name == "list the mount" and "MOUNT=" in r.stdout:
                    print(f"             mount contents: {r.stdout.strip()[6:80]}")
                    escaped = any(x in r.stdout for x in
                                  (".env", "problems", "knowledge.db", "corpus", "services"))
                print(f"  {'ESCAPED' if escaped else 'contained':<10} {name:<18} "
                      f"rc={r.exit_code} timed_out={r.timed_out} {out[:40]!r}")
                fails += bool(escaped)
        finally:
            E.set_sandbox(None)

    banner("VERDICT")
    print(f"  host and container agree, fitter intact, hostile code contained: "
          f"{'YES' if not fails else 'NO'}")
    print("\n  " + ("SANDBOX WIRING VERIFIED" if not fails
                    else f"{fails} FAILURE(S) — the seam is not trustworthy"))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
