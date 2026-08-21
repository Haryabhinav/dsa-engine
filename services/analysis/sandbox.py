"""Container-isolated execution.

STATUS: VERIFIED. `python services/analysis/sandbox.py selftest` passes -- egress
blocked, fork bomb contained, memory bomb contained, filesystem read-only -- and
`scripts/verify_sandbox_wiring.py` additionally proves the ENGINE routes through
it, containing 7 hostile submissions including one that read the reference
solution and one that read the API key out of an over-broad mount (F29).

Those are two separate claims and both are needed: the selftest says the controls
work, the wiring test says something actually uses them. This module sat here for
five sessions, imported by nothing, while the isolation was reported as built.

Isolation model, and what each control actually stops:

  --network=none                exfiltration, callbacks, crypto mining
  --read-only + tmpfs           persistence, disk exhaustion
  --memory / --memory-swap      OOM of the host
  --pids-limit                  FORK BOMBS  (the control people forget)
  --cpus                        CPU monopolisation
  --cap-drop=ALL                privilege escalation primitives
  --security-opt no-new-privs   setuid escalation
  -u nobody                     filesystem damage inside the container
  orchestrator wall clock       everything above being ignored

The last line is the important one and is enforced in `engine.run`, OUTSIDE the
container: a timeout enforced by the sandboxed process is defeatable by the
sandboxed process.

gVisor (`--runtime=runsc`) is the intended production runtime and is applied when
`DSA_RUNTIME=runsc` is set. It requires a **Linux host** — it does not run under
Docker Desktop on Windows, so it is opt-in rather than default.
"""
from __future__ import annotations

import os
import pathlib
import re
import uuid
from typing import Optional
import shlex

from engine import RunResult, run

IMAGE = os.environ.get("DSA_SANDBOX_IMAGE", "dsa-runner:latest")
RUNTIME = os.environ.get("DSA_RUNTIME", "")          # "runsc" on a Linux host
MEM = os.environ.get("DSA_SANDBOX_MEM", "256m")
CPUS = os.environ.get("DSA_SANDBOX_CPUS", "1.0")
PIDS = os.environ.get("DSA_SANDBOX_PIDS", "64")


def available() -> bool:
    return run(["docker", "info", "--format", "{{.ServerVersion}}"], "", 8000).ok


def docker_argv(workdir: pathlib.Path, inner: list[str]) -> list[str]:
    argv = [
        "docker", "run", "--rm", "-i",
        "--network=none",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=64m,noexec",
        f"--memory={MEM}", f"--memory-swap={MEM}",
        f"--cpus={CPUS}",
        f"--pids-limit={PIDS}",
        "--cap-drop=ALL",
        "--security-opt", "no-new-privileges",
        "-u", "65534:65534",
        "-v", f"{workdir.resolve()}:/work:ro",
        "-w", "/work",
    ]
    if RUNTIME:
        argv += [f"--runtime={RUNTIME}"]
    return argv + [IMAGE] + inner


def run_in_container(workdir: pathlib.Path, inner: list[str], stdin: str = "",
                     timeout_ms: int = 10000) -> RunResult:
    """Wall clock is still owned by the caller — `run` kills the docker client,
    and `--rm` reaps the container."""
    return run(docker_argv(workdir, inner), stdin, timeout_ms)


ORPHAN_RE = re.compile(r"^dsa-[0-9a-f]{10}$")


def reap_orphans() -> int:
    """Remove containers left behind by a previous process.

    Deliberately narrow: only names matching our own session pattern
    (`dsa-` + 10 hex). A broad `dsa-*` sweep would delete compose services like
    `dsa-engine-postgres-1`, which is someone's database.
    """
    r = run(["docker", "ps", "-a", "--format", "{{.Names}}"], "", 20000)
    if not r.ok:
        return 0
    names = [n.strip() for n in r.stdout.splitlines() if ORPHAN_RE.match(n.strip())]
    for n in names:
        run(["docker", "rm", "-f", n], "", 30000)
    return len(names)


class Session:
    """ONE long-lived container; `docker exec` per execution.

    Why not `docker run` per execution, which is simpler and needs no cleanup:
    it is 26x too noisy to measure with. Measured on this host, no-op program,
    9 runs each (BUILD_LOG F28):

        host subprocess          median   47 ms   jitter    18 ms
        docker run  per exec     median  670 ms   jitter   317 ms   <- unusable
        docker exec per exec     median  172 ms   jitter    26 ms   <- CV 5.1%

    The complexity fitter resolves timings against a 12 ms signal floor. 317 ms
    of startup jitter is 26x that floor: wiring `docker run` into the hot path
    would have kept every correctness test green while silently destroying the
    Theta(.) verdicts -- the failure mode is a WRONG COMPLEXITY ANSWER, not a
    crash, so nothing would have told us.

    With a persistent container the 172 ms is a CONSTANT, which baseline
    subtraction already removes, and the residual 26 ms is handled by
    minimum-of-k. Isolation is unchanged: every flag lives on the container, and
    `docker exec` cannot re-grant what `docker run` dropped.

    Two mounts, deliberately:
      /work   the submission, READ-ONLY -- code under test cannot rewrite itself
      /build  tmpfs, writable AND executable -- compiler output lands here

    /tmp stays `noexec`, so a compiled binary cannot be run from it. That is the
    point: only the compiler's own output directory is executable.
    """

    def __init__(self, workdir: pathlib.Path, name: Optional[str] = None):
        self.workdir = pathlib.Path(workdir).resolve()
        self.name = name or f"dsa-{uuid.uuid4().hex[:10]}"
        self.started = False

    def start(self) -> "Session":
        if self.started:
            return self
        argv = [a for a in docker_argv(self.workdir, []) if a not in ("--rm", "-i")]
        argv = argv[:2] + ["-d", "--name", self.name] + argv[2:]
        # writable+executable scratch for compiler output; /tmp stays noexec
        # `exec` is REQUIRED and not the default. Docker mounts --tmpfs with
        # rw,noexec,nosuid by default, so the compiler wrote a binary here and
        # then could not run it: rc=126, "permission denied" (BUILD_LOG F33).
        # The comment above claimed this mount was executable; nothing had ever
        # checked, because no C++ submission had been run inside a container.
        argv = argv[:-1] + ["--tmpfs", "/build:rw,exec,size=128m", argv[-1]]
        r = run(argv + ["sleep", "86400"], "", 60000)
        if not r.ok:
            raise RuntimeError(f"could not start sandbox container: {(r.stderr or '').strip()[:200]}")
        self.started = True
        return self

    def exec(self, inner: list[str], stdin: str = "", timeout_ms: int = 10000) -> RunResult:
        """Wall clock stays with the caller: `run` kills the docker CLI, and the
        container's own limits stop anything the kill leaves behind."""
        if not self.started:
            self.start()
        return run(["docker", "exec", "-i", "-w", "/work", self.name] + inner,
                   stdin, timeout_ms)

    def close(self) -> None:
        if self.started:
            run(["docker", "rm", "-f", self.name], "", 30000)
            self.started = False

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.close()


SELFTEST = [
    ("network egress blocked", ["python", "-c",
        "import socket;socket.create_connection(('1.1.1.1',53),2)"], False),
    ("fork bomb contained", ["python", "-c",
        "import os\nwhile True: os.fork()"], False),
    ("memory bomb contained", ["python", "-c",
        "b=[];\nwhile True: b.append(' '*10**7)"], False),
    ("filesystem read-only", ["python", "-c",
        "open('/work/x','w').write('x')"], False),
    ("ordinary program runs", ["python", "-c", "print(6*7)"], True),
]


def selftest() -> int:
    if not available():
        print("docker daemon not reachable — cannot verify isolation.")
        print("start Docker Desktop, then:  python -m sandbox selftest")
        return 2
    here = pathlib.Path(__file__).parent
    bad = 0
    for name, inner, should_succeed in SELFTEST:
        r = run_in_container(here, inner, "", 15000)
        ok = r.ok if should_succeed else (not r.ok)
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            bad += 1
            print(f"        {shlex.join(inner)[:70]} -> rc={r.exit_code}")
    print(f"\n  {'SANDBOX VERIFIED' if not bad else f'{bad} CONTROL(S) FAILED'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    import sys
    sys.exit(selftest())
