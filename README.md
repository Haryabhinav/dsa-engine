# DSA Diagnosis Engine

Deterministic diagnosis for competitive-programming submissions. The engine
**proves** what is wrong before anything explains it — sandboxed execution,
differential oracles, delta-debugging, AST mutation and empirical complexity
fitting. No LLM is involved in reaching a verdict.

Spec: `../Research/DSA-Module-Technical-Spec.md` · Authoring: `PROBLEM_CONTRACT.md`

---

## Status

| Stage | Capability | State |
|---|---|---|
| S0 | Oracle validation gate | ✅ working |
| S1 | Correctness verdict | ✅ working |
| S2 | **Test 42** — minimal counterexample | ✅ working |
| S3 | **Bisect** — PROVEN / LOCALIZED / STRUCTURAL | ✅ working |
| S4 | **Complexity** — empirical exponent + budget | ✅ working |
| S5 | **Forge** — robustness gate, latent-bug hunt | ✅ working |
| S6 | **Halflife** — concept DAG, coupled decay, review scheduling | ✅ working |
| — | **Container isolation** — wired into `engine.run`, on by default at the gateway | ✅ verified: 7 hostile submissions contained |
| — | **Hint layer + firewall + red-team gate** | ✅ working — red-teamed against a **live** model, incl. prompt injection |
| — | **Gateway** — FastAPI + async SSE, load-tested at 25 concurrent streams | ✅ working |
| — | **Store** — dialect-aware: SQLite ✅ · Postgres ✅ verified on a live server |  |
| — | **Semantic layer** — Qdrant local + fastembed, floor-gated | ✅ working |
| — | **C++** end to end (Java deliberately dropped — see BUILD_LOG S5) | ✅ |

**Python + C++. Subprocess isolation only.** Safe for code you authored; **not**
safe for untrusted submissions from real users. See *Known limits*.

---

## Run it

```bash
# 0. seed the concept DAG (once)
python scripts/seed_concepts.py

# 1. validate a problem's oracles (must pass before the problem is served)
python services/analysis/cascade.py gate problems/pair-sum-count --trials 60

# 2. diagnose a submission
python services/analysis/cascade.py diagnose problems/pair-sum-count corpus/wrong_selfpair.py

# 3. firewall red-team gate — must pass before any hint reaches a human
python scripts/redteam.py

# 4. does coupled scheduling actually help? (simulation, prints a threshold)
python scripts/calibrate.py

# 5. build the semantic index (concepts, problems, misconceptions)
python scripts/index_semantic.py
python scripts/try_semantic.py           # incl. the queries it should REFUSE

# 6. demo UI
python services/gateway/app.py           # -> http://127.0.0.1:877
```

**The LLM is optional and off by default.** The hint generator uses the offline
stub unless `allow_network=True` is passed deliberately, so tests and the
red-team suite spend nothing. With a key in `.env` (gitignored) the live path is
exercised by `scripts/redteam_live.py`. The Gemini
adapter refuses to reach the network unless `allow_network=True` is passed
deliberately.

Stdlib only, except the semantic layer: `pip install "qdrant-client[fastembed]"`
(local mode — no server, no API key, no per-call cost).

---

## What it actually produces

**Test 42** on a self-pairing bug — shrunk from a 10-element random failure to a
single element:

```
S2 · Test 42 — minimal counterexample
  found at seed=6 n=10, shrinking…
  shrink: 10 → 5 → 3 → 2 → 1

  minimal input   1 16 | 8
  your output     1
  expected        0
```

**Bisect**, proving the defect rather than guessing it:

```
S3 · Bisect — fault localization
  suite: 5 failing / 8 passing · 18 mutation sites, 10 tried after coverage pruning
  tier: PROVEN
  defect proven at line 11
  [RESTRICTED — never leaves the server: L11: '<=' -> '<'  [cmp]]
```

**Complexity**, with the arithmetic stated:

```
S4 · Complexity
  n=1000  73.3 ms · n=2000  298.7 ms · n=4000  872.2 ms · n=8000  3432.4 ms
  empirical exponent: k = 1.82 ± 0.13   (t ~ n^k, 95% CI)
  measured Θ(n^2)   required Θ(n)  →  needs O(n)
  at n=200,000: ~4.00e+10 ops vs budget ~4.00e+08
```

**Forge**, on an accepted solution:

```
S5 · Forge — robustness gate
  mutation score: 0.93  (13/14 mutants killed)
  1 survived — tested behaviour is under-specified
    L7: '2' -> '3'  [const]          # equivalent mutant: d[2:2+n] == d[2:3+n]
  status: MASTERED
```

---

## Design decisions worth knowing

**Oracle disagreement quarantines the problem, never blames the student.** If
`reference` and `brute` disagree on any small random input, the bundle is marked
untrusted and no verdict is issued.

**Three localization tiers, never conflated.** `PROVEN` requires a single
mutation that flips the whole suite. `LOCALIZED` is Ochiai spectrum analysis, and
is only claimed when the failing and passing coverage actually *differ* — if
every line runs on every input there is no localization, and the verdict degrades
to `STRUCTURAL` rather than fabricating precision.

**Coverage-guided mutation pruning is sound, not heuristic.** A mutation on a line
no failing test executes cannot change the failing outcome, so it is skipped.

**Shrinking preserves two invariants on every candidate:** still constraint-valid
(re-checked by `validator.py`) and still failure-inducing. A shrink breaking
either is rejected and the search backtracks. An unverified shrink is never
returned.

**Complexity is named by effective exponent, not R².** R² saturates at 1.000 for
every plausible model — `n²` and `n² log n` are indistinguishable by fit quality.
The log–log slope and its confidence interval are what discriminate.

**Timing uses minimum-of-k, not median.** Measurement noise is strictly one-sided
(interference only adds time), so the fastest observed run is the best estimator.

**`INCONCLUSIVE` is a first-class verdict.** When the exponent CI is too wide or
too few points clear the noise floor, the engine refuses to name a class.

---

## Known limits (measured, not assumed)

**Benchmark variance is 4–10% CV on this machine**, against the spec's 3% gate.
Process-level wall-clock timing on Windows without core pinning cannot do better.
The exponent CI stays tight enough to be conclusive on super-linear code, which
suggests **the spec's acceptance criterion was measuring the wrong thing** — the
gate belongs on the fitted slope's CI, not on per-measurement variance.

**Fast linear solutions are near the resolution limit.** At `n_max = 200000` a
linear Python solution does ~90 ms of work; stepping down leaves only 3–5 points
above the noise floor. Verdicts are correct but the exponent is biased low by
residual fixed costs. Real fix: in-process instrumentation or operation counting.

**Mutation repair search does not find every bug — confirmed.** `wrong_selfpair`
(one comparison token off) resolves to `PROVEN`. `wrong_double_count` (structurally
wrong counting) finds no single-token repair and correctly falls back. This is
risk **R1** from the spec, reproducing exactly as predicted, and it is why the
tier system exists.

**Subprocess isolation is not a security boundary.** No cgroups, no seccomp, no
network isolation, no memory cap (Windows lacks `resource`). gVisor requires a
Linux host and does not run under Docker Desktop on Windows. Do not point this at
untrusted code.

---

## Layout

```
problems/<slug>/     bundle: reference, brute, generator(s), validator, samples
corpus/              student submissions used as test fixtures
services/analysis/
  engine.py          harness · oracle gate · stress · shrinker · complexity
  mutate.py          DSA mutation catalog · byte-range splicing
  localize.py        Ochiai SBFL · repair search · Forge
  knowledge.py       concept DAG · SCC · transitive reduction · coupled decay
  hints.py           context broker (tier views) · output firewall · retry/fallback
  semantic.py        Qdrant local + fastembed · floor-gated suggestion (never decision)
  store.py           dialect-aware persistence — SQLite dev / Postgres deployment
  sandbox.py         container isolation — Session (persistent) + selftest
  llm.py             provider seam — stub by default, Gemini behind allow_network
  covrun.py          settrace coverage wrapper (no third-party deps)
  cascade.py         CLI
knowledge.db         SQLite: concepts, edges, closure, mastery, review events
scripts/             bundle seeding, concept seeding, redteam.py, harnesses
```

---

## Coupled decay in one table

```
concept                         own     eff
Dijkstra's algorithm           0.79    0.34
Priority queues                0.12    0.05
Graph representation           0.05    0.02
```

Dijkstra was reviewed three days ago. Independent spaced repetition believes it
is 79 % retained and would not schedule it. Coupled through its rotted
prerequisites the real figure is 34 %. That gap is the whole argument for the
feature.

**Not yet validated.** Coupled decay is *demonstrated*, not *proven better* than
independent scheduling. That needs the simulated-learner harness measuring
retention and calibration on held-out learners. Until it exists, describe this as
a well-reasoned hypothesis. 


## Read this before believing the pitch

The one-token repair search (PROVEN) is the deepest component here and the
narrowest: measured against 35 real human fixes, **8%** were within its reach and
**62%** were rewrites. What generalises is cheaper and less glamorous —
**Test 42**, which shrinks a 5000-element failing input to two numbers regardless
of how large the real fix is, and **STRUCTURAL**, which declines to point at a
line when the approach itself is wrong. Lead with those.

## What is still untested

Everything above has been executed. None of it has met a student.

| Claim | Status |
|---|---|
| The engine runs, isolates, measures, and refuses to leak | **verified** — see BUILD_LOG |
| Mutation search finds *real* bugs at a useful rate | **measured** — 64 pairs, bugs from a source independent of the operator catalog. In-catalog **100% PROVEN**; out-of-catalog 34.8%. False alarms on correct code **0/11**. See BUILD_LOG session 9 |
| LOCALIZED points at the right place | **measured and it does not** — band accuracy **16.7%** (3/18). Documented, not fixed. Treat LOCALIZED as "we could not prove it", not as a location |
| Problems are authorable by someone other than me | **untested.** Ten problems now exist; all ten were written by the same person who wrote the contract they satisfy |
| These bugs resemble real human bugs | **measured, and they do not.** 35 real WA→AC fixes from a live Codeforces history: **8% are ≤1 line, 62% are rewrites of >10 lines.** A single-token repair search can reach at most 8% of them. Caveat: n=35, one strong competitor; learners may differ. See BUILD_LOG session 9b |
| Hints help a human learn | **untested.** The firewall proves the model cannot leak the answer. It proves nothing about whether the nudge teaches |
| Spaced repetition improves retention | **simulated only**, and the simulator honestly reports NO RELIABLE IMPROVEMENT above ~1 review/day. The calibration gain is real; the retention gain is not established |

The distinction that matters: the *machinery* is tested, the *product claim* is
not. Anyone reading this repo should treat "it works" as a statement about
software, not about pedagogy.

## Isolation, and how to check it yourself

Student code runs in a container by default at the gateway. Two separate
questions, two separate tests — the first proves the container works, the second
proves the engine *uses* it:

```bash
docker build -t dsa-runner:latest .
python services/analysis/sandbox.py selftest     # do the controls hold?
python scripts/verify_sandbox_wiring.py          # does the ENGINE go through them?
```

The wiring test is the one that matters. `sandbox.py` sat in this repo for five
sessions, imported by nothing, while every submission ran as a bare host
subprocess — see BUILD_LOG F29. It checks three things: host and container reach
the same verdict, the complexity fitter survives the container, and seven hostile
submissions (egress, fork bomb, memory bomb, disk write, reading the reference
solution, reading `.env`, listing the mount) are all contained.

**The mount is the blast radius.** It contains the submission and nothing else.
Mounting the repository root — the obvious first move — makes every reference
solution and the API key readable from inside the sandbox.

`DSA_SANDBOX=0` disables isolation for host-only debugging. The UI says
`NOT isolated` when it is off; it never pretends.

## Postgres

```bash
docker compose up -d postgres
export DSA_DATABASE_URL=postgresql://dsa:dsa@localhost:5432/dsa
python scripts/verify_postgres.py     # placeholders, upsert, IDENTITY, closure
python scripts/seed_concepts.py       # then the real 38-concept graph
```

Unset `DSA_DATABASE_URL` and everything runs on SQLite with identical results.
The migration is *not* "a connection-string change" — see BUILD_LOG S7.1 for the
four real dialect incompatibilities.

## Live model

```bash
echo "GEMINI_API_KEY=..." > .env        # gitignored; never in source
python scripts/redteam_live.py         # spends a few credits
```

