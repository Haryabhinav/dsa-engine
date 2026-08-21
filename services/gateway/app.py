"""Gateway — FastAPI + async SSE.

Replaces the stdlib `ThreadingHTTPServer` prototype. The reason is specific, not
fashion:

    SSE connections are LONG-LIVED. A student watching a cascade holds one open
    for up to two minutes. Under thread-per-connection that is one OS thread per
    watching student, and the server falls over in the low hundreds. Under an
    event loop an idle streaming connection costs a coroutine and a socket.

Note what this does NOT claim. The analysis work is blocking subprocess
orchestration and still needs a real thread — it runs in a worker pool. What the
event loop buys is that the *connection* no longer costs a thread, which is
exactly where the SSE workload was expensive.

This is also where the spec's dual-stack premise gets settled. The original
argument for a Node gateway was three-part: Babel for AST work (we use Python's
`ast` and a token lexer), V8 isolates for sandboxing (we do not execute JS), and
an event loop for concurrent long-lived connections. Only the third survived
implementation — and asyncio provides it without a second language, a second
toolchain, or a shared-types package to keep in sync.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib
import shutil
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "analysis"))

import engine as ENG         # noqa: E402
import hints as H            # noqa: E402
import llm as L              # noqa: E402
import sandbox as SBX        # noqa: E402
import tutor as T            # noqa: E402
import localize as lz        # noqa: E402
from engine import (Problem, fit_complexity, run, shrink_int_array,  # noqa: E402
                    solution_cmd, stress)

STATIC = pathlib.Path(__file__).parent / "static"

# Isolation is ON by default at the gateway, because this is the only place
# untrusted code enters the system. It degrades to host execution ONLY if the
# daemon is unreachable, and when it does the UI says so rather than pretending.
SANDBOX = os.environ.get("DSA_SANDBOX", "1") != "0"
SANDBOX_OK = False

# Live hints are ON when a key is present. DSA_LLM=0 forces the deterministic
# stub, which is what CI and the red-team suite use so tests never spend credits.
L._load_env()
LLM_ON = os.environ.get("DSA_LLM", "1") != "0" and bool(os.environ.get("GEMINI_API_KEY"))
RUNS: dict[str, dict] = {}

# --------------------------------------------------------------------------
# TWO POOLS, deliberately (BUILD_LOG F24).
#
# `asyncio.to_thread` uses ONE shared default executor. Load testing with 25
# concurrent cascades saturated it, and a trivial /api/hint call then timed out
# behind them -- head-of-line blocking between slow work and fast work sharing a
# queue. The connections were cheap (that was the point of the event loop); the
# WORK POOL was the real bottleneck, and it was unbounded and shared.
#
# Cascades get a small bounded pool sized to the machine, because each one is
# subprocess-heavy and more concurrency buys nothing but contention. Hints get
# their own tiny pool so a fast path is never queued behind a slow one.
CPU = os.cpu_count() or 4
CASCADE_POOL = ThreadPoolExecutor(max_workers=max(2, CPU - 1), thread_name_prefix="cascade")
HINT_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hint")
MAX_QUEUED = max(2, CPU - 1) * 4        # admission control: refuse, do not starve
_inflight = 0

@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Probe the daemon ONCE at startup, not per request: `docker info` costs
    ~200 ms and would otherwise be paid on every submission."""
    global SANDBOX_OK
    SANDBOX_OK = SANDBOX and await asyncio.get_running_loop().run_in_executor(
        HINT_POOL, SBX.available)
    print(f"  isolation: {'ON (docker)' if SANDBOX_OK else 'OFF - host execution'}")
    if SANDBOX_OK:
        # Reap containers orphaned by a PREVIOUS process. A session cleans up in
        # its own `finally`, which is exactly what does not run when the server is
        # killed -- and this server was killed several times today, each time
        # leaving a container holding memory and a name (F46). Matches only our
        # own session naming (`dsa-` + 10 hex) so compose services such as
        # dsa-engine-postgres-1 are never touched.
        n = await asyncio.get_running_loop().run_in_executor(HINT_POOL, SBX.reap_orphans)
        if n:
            print(f"  reaped {n} orphaned container(s) from a previous run")
    print(f"  hints    : {'LIVE gemini (stub on failure)' if LLM_ON else 'stub only'}")
    yield
    for pool in (CASCADE_POOL, HINT_POOL):
        pool.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="DSA Diagnosis Engine", docs_url="/api/docs", lifespan=lifespan)


class DiagnoseIn(BaseModel):
    problem: str
    code: str
    ext: str = ".py"
    student: Optional[str] = None


class HintIn(BaseModel):
    run: str
    tier: int = 0
    guess: Optional[str] = None


# --------------------------------------------------------------------------
def _cascade(run_id: str, problem_dir: str, code: str, ext: str,
             loop: asyncio.AbstractEventLoop, student: Optional[str] = None) -> None:
    """Blocking. Runs in a worker thread; results are handed to the event loop
    through a thread-safe put so the SSE generator can await them."""
    st = RUNS[run_id]
    q: asyncio.Queue = st["q"]
    sess = None
    box = ROOT / ".scratch" / run_id

    def emit(stage: str, status: str, **kw) -> None:
        loop.call_soon_threadsafe(q.put_nowait, {"stage": stage, "status": status, **kw})

    try:
        p = Problem.load(ROOT / problem_dir)
        # A PER-RUN mount holding only this submission. Never the repo root:
        # whatever is mounted is readable by the code under test, and the repo
        # root contains every reference solution and the API key (F29).
        box = ROOT / ".scratch" / run_id
        box.mkdir(parents=True, exist_ok=True)
        sub = box / f"sub{ext}"
        sub.write_text(code, encoding="utf-8")
        st["code"] = code

        if SANDBOX and SANDBOX_OK:
            sess = SBX.Session(box).start()
            ENG.set_sandbox(sess)          # thread-local: this worker only

        iso = ("isolated" if ENG.sandbox_active()
               else "NOT isolated — host execution")
        emit("S0", "done",
             detail=f"{p.meta['slug']} · required Θ({p.meta['required_complexity']}) · {iso}",
             isolated=ENG.sandbox_active())

        emit("S1", "running", detail="running the visible sample tests")
        bad = [(o, run(solution_cmd(sub), i, 5000).out) for i, o in p.samples()]
        fails = [(o, g) for o, g in bad if g != o]
        emit("S1", "done", ok=not fails,
             detail="samples pass" if not fails
                    else f"expected {fails[0][0]!r}, got {fails[0][1]!r}")

        emit("S2", "running", detail="trying random inputs to find one where you are wrong "
                                       "(this is the slow part - up to a minute)")
        ce = stress(p, sub, max_seeds=60)
        if ce is None:
            emit("S2", "done", ok=True,
                 detail="no disagreement found in 60 random tests")
            # NOTHING TO LOCATE is not STRUCTURAL. `localize` returns STRUCTURAL
            # when there are no failing cases, which is correct internally and a
            # lie on screen: STRUCTURAL means "your approach is wrong", and
            # telling a student with a CORRECT solution that their approach is
            # wrong is the worst possible misreport (BUILD_LOG F44). Complexity
            # still runs -- a correct answer can still be too slow.
            emit("S3", "done", skipped=True,
                 detail="nothing to locate - no input was found where your answer differs")
        else:
            emit("S2", "running", detail=f"found at n={ce.n}, shrinking...")
            small = shrink_int_array(p, sub, ce)
            st["counterexample"] = {"input": small.input.strip(),
                                    "expected": small.expected, "actual": small.actual}
            kind = getattr(small, "kind", "wrong_answer")
            emit("S2", "done", ok=False, kind=kind,
                 chain=" -> ".join(map(str, small.shrink_steps)),
                 input=small.input.strip(), expected=small.expected, actual=small.actual)
            if kind == "runtime_error":
                # A crash is not a wrong answer. There is no output to compare,
                # so a repair search over expected-vs-actual and a timing fit are
                # both meaningless -- and running them anyway produced a green
                # tick on STRUCTURAL and a fabricated `k = 0 +/- 0` for a real
                # user (BUILD_LOG F40). Stop here and say what happened.
                emit("S3", "done", skipped=True,
                     detail="skipped - your program crashed, so there is no wrong "
                            "answer to localise. Fix the crash first.")
                emit("S4", "done", skipped=True,
                     detail="skipped - cannot time a program that does not run.")
                # A crash IS a failed attempt and must reach the scheduler. The
                # early return skipped the return edge entirely, so a student who
                # kept crashing would have looked, to the scheduler, like a
                # student who never practised.
                if student:
                    try:
                        rec = T.record_attempt(student,
                                               pathlib.Path(problem_dir).name, False)
                        emit("recorded", "done", **rec)
                    except Exception as e:
                        emit("recorded", "done", solved=False, error=repr(e)[:120])
                emit("done", "done")
                return

        if ce is not None:
            emit("S3", "running",
                 detail="testing one-token changes to see if any makes every test pass")
        loc, fails_c, _ = (lz.localize(p, sub) if ce is not None
                           else (lz.Localization("STRUCTURAL"), [], []))
        st["fault_sig"] = loc.fault_sig if loc.tier == "PROVEN" else None
        st.update(tier=loc.tier, span=loc.patch_line,
                  concepts=[c["id"] for c in p.meta.get("concepts", [])],
                  repair={"repl": (loc.patch or "").split("-> ")[-1].strip("' []cmpbinoolst")})
        if ce is not None:
            emit("S3", "done", tier=loc.tier, line=loc.patch_line,
                 sites=loc.total_sites, tried=loc.tried,
                 band=[l for l, _ in loc.lines[:3]] if loc.tier == "LOCALIZED" else [])

        emit("S4", "running",
             detail="running your code at the largest input against the time limit")
        j = ENG.judge(p, sub)
        fit = fit_complexity(p, sub, trials=3)
        band = ENG.reconcile(j, ENG.growth_band(fit))
        st["complexity"] = {"measured": fit.best,
                            "required": p.meta["required_complexity"]}
        # The JUDGE verdict is the headline, because it is the robust claim and the
        # one a competitive programmer acts on. The growth band is secondary and
        # omitted when the data cannot support it. The fine n vs n log n claim is
        # gone: it needs an exponent resolved to ~0.09, which is not achievable on
        # a working laptop, and three attempts to make it reliable all failed
        # (F30, F42, F44). Raw timings still travel, but the UI hides them.
        st["speed_ok"] = bool(j["ok"])
        emit("S4", "done", ok=j["ok"], judge=j, band=band,
             required=p.meta["required_complexity"],
             k=round(fit.exponent, 2), ci=round(fit.ci95, 2),
             noise=round(fit.noise_ratio, 2),
             points=[[n, round(t, 1)] for n, t in fit.points])

        # THE RETURN EDGE. Without this the scheduler is a static ranking that
        # never learns, and "spaced repetition" is a claim rather than a
        # behaviour (F47). Solved == the differential search found no
        # disagreement AND the judge accepted the running time.
        if student:
            solved = bool(ce is None and st.get("speed_ok"))
            try:
                rec = T.record_attempt(student, pathlib.Path(problem_dir).name,
                                       solved, fault_sig=st.get("fault_sig"))
                emit("recorded", "done", **rec)
            except Exception as e:                    # never fail a diagnosis
                emit("recorded", "done", solved=solved, error=repr(e)[:120])

        emit("done", "done")
    except ENG.InfrastructureError as e:
        # OUR failure. Say so plainly. The one thing this must never do is
        # render as a verdict about the student's code (F34).
        emit("error", "failed", ours=True,
             detail=f"We could not run your code — this is a problem on our side, "
                    f"not with your solution. Nothing has been recorded against "
                    f"your progress. ({str(e)[:120]})")
    except Exception as e:
        emit("error", "failed", detail=repr(e)[:200])
    finally:
        # Tear the container down on EVERY path, including the exception path.
        # A leaked container holds memory and a name that the next run collides
        # with; a leaked mount holds the student's source on disk.
        ENG.set_sandbox(None)
        if sess is not None:
            sess.close()
        shutil.rmtree(box, ignore_errors=True)
        loop.call_soon_threadsafe(q.put_nowait, None)


# --------------------------------------------------------------------------
APP_DIR = STATIC / "app"          # built React bundle (vite build)


@app.get("/app")
@app.get("/app/")
async def react_index() -> FileResponse:
    """The React UI. Served by FastAPI from the built bundle so deployment stays
    ONE process -- no separate node server to run or supervise."""
    f = APP_DIR / "index.html"
    if not f.exists():
        raise HTTPException(503, "UI not built. Run: cd services/gateway/ui && npm run build")
    return FileResponse(f, headers={"Cache-Control": "no-store"})


@app.get("/app/assets/{name}")
async def react_asset(name: str) -> FileResponse:
    # Explicit whitelist rather than StaticFiles: the filename comes from a URL,
    # and resolving it inside APP_DIR is what stops `../../.env` from being a
    # valid asset request. Hashed bundle names are immutable, so they cache hard.
    f = (APP_DIR / "assets" / name).resolve()
    if not f.is_file() or APP_DIR.resolve() not in f.parents:
        raise HTTPException(404, "no such asset")
    return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/")
async def index() -> FileResponse:
    # no-store, deliberately. FileResponse sends an ETag, and a 304 served a
    # STALE bundle after a fix had already landed on disk -- which cost real
    # debugging time chasing a bug that was already fixed (BUILD_LOG F25).
    # The page is a few KB; there is nothing to gain by caching it.
    # Prefer the built React app; fall back to the single-file vanilla page when
    # the bundle is absent, so a fresh clone still works before `npm install`.
    built = APP_DIR / "index.html"
    target = built if built.exists() else STATIC / "index.html"
    return FileResponse(target, headers={"Cache-Control": "no-store, must-revalidate"})


@app.get("/api/problems")
async def problems() -> list[str]:
    return sorted(d.name for d in (ROOT / "problems").iterdir() if d.is_dir())


@app.post("/api/diagnose")
async def diagnose(body: DiagnoseIn) -> dict:
    global _inflight
    # Admission control. Accepting work we cannot start is worse than refusing
    # it: the client waits on a stream that will not move for minutes.
    if _inflight >= MAX_QUEUED:
        raise HTTPException(503, "analysis queue full; retry shortly",
                            headers={"Retry-After": "20"})
    rid = uuid.uuid4().hex[:12]
    RUNS[rid] = {"q": asyncio.Queue(), "unlocked": 0}
    loop = asyncio.get_running_loop()
    _inflight += 1

    def done(_fut):
        global _inflight
        _inflight -= 1

    student = body.student if T.valid_handle(body.student or "") else None
    RUNS[rid]["student"] = student
    fut = loop.run_in_executor(CASCADE_POOL, _cascade, rid, body.problem,
                               body.code, body.ext, loop, student)
    fut.add_done_callback(done)
    return {"run": rid, "queued": _inflight}


@app.get("/api/stream")
async def stream(run: str) -> StreamingResponse:
    st = RUNS.get(run)
    if not st:
        raise HTTPException(404, "unknown run")

    async def gen() -> AsyncIterator[bytes]:
        q: asyncio.Queue = st["q"]
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=20.0)
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"     # keeps proxies from closing the stream
                continue
            if ev is None:
                break
            yield f"data: {json.dumps(ev)}\n\n".encode()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _make_hint(report: dict, tier: int, code: str):
    """Live model first, deterministic stub as the fail-safe.

    Until now the gateway passed NO generator, so `generate_hint` silently used
    its default `stub_generator` and every hint a user ever saw in the UI was
    template text. The Gemini path was built, firewalled and red-teamed against a
    live model -- and reachable only from a script (BUILD_LOG F41). Wired, tested,
    and unused is the same failure as sandbox.py in F29.

    Degradation is deliberate and one-way: if the model errors, is rate limited,
    or has no key, the student still gets the stub's hint rather than an error.
    `generate_hint` swallows generator exceptions into `rejections`, so the check
    below inspects those instead of catching -- otherwise a network failure would
    silently deliver the CANNED fallback, which is far worse than the stub.

    The returned source string is reported to the client and shown in the UI:
    which brain produced a hint should be visible, not hidden.
    """
    if LLM_ON:
        client = L.GeminiClient(L.LLMConfig(provider="gemini", allow_network=True,
                                            model="", max_output_tokens=400))

        def gen(view, prior_rejections):
            return client.complete(
                L.SYSTEM_PROMPT,
                L.build_prompt(view.data, view.tier, code, prior_rejections))

        try:
            r = H.generate_hint(report, tier, code, generator=gen)
            broke = any("generator raised" in x for x in r.rejections)
            if not broke:
                return r, f"gemini:{client.last_model or '?'}"
        except Exception:
            pass
    return H.generate_hint(report, tier, code), "stub"


@app.post("/api/hint")
async def hint(body: HintIn) -> dict:
    st = RUNS.get(body.run)
    if not st:
        raise HTTPException(404, "unknown run")
    # The predict-first gate is enforced HERE, server-side, so it cannot be
    # bypassed from the client. 428 Precondition Required is the honest code.
    if body.tier > 0 and not (body.guess or "").strip():
        raise HTTPException(428, "prediction required")

    report = {
        "concepts": st.get("concepts", []),
        "fault_class": st.get("tier", "STRUCTURAL"),
        "spans": [{"line": st["span"]}] if st.get("span") else [],
        "counterexample": st.get("counterexample", {}),
        "complexity": st.get("complexity", {}),
        "repair": st.get("repair", {}),
    }
    loop = asyncio.get_running_loop()
    res, src = await loop.run_in_executor(HINT_POOL, _make_hint, report,
                                          body.tier, st.get("code", ""))
    st["unlocked"] = max(st["unlocked"], body.tier)
    return {"tier": body.tier, "text": res.text, "fell_back": res.fell_back,
            "source": src, "rejections": res.rejections[:3]}


@app.get("/api/next")
async def next_up(student: str) -> dict:
    if not T.valid_handle(student):
        raise HTTPException(400, "handle must be 2-40 chars of [A-Za-z0-9_.-]")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(HINT_POOL, T.next_up, student)


@app.get("/api/progress")
async def progress(student: str) -> dict:
    if not T.valid_handle(student):
        raise HTTPException(400, "handle must be 2-40 chars of [A-Za-z0-9_.-]")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(HINT_POOL, T.progress, student)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "sandbox": SANDBOX and SANDBOX_OK, "llm": LLM_ON,
            "runs": len(RUNS), "inflight": _inflight,
            "cascade_workers": CASCADE_POOL._max_workers, "max_queued": MAX_QUEUED}




if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 877
    print(f"\n  DSA engine UI  ->  http://127.0.0.1:{port}\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
