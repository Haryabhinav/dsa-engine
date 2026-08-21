"""The hint layer and its firewall — the "Firewalling" half of Bisect.

Two controls, in strict order of importance:

  1. CONTEXT ISOLATION (primary). The generator is handed a capability *view*
     that structurally cannot contain the repair patch, the reference solution,
     or the ablation program. A model cannot leak what it was never given.

  2. OUTPUT FIREWALL (secondary, defence in depth). Every generated hint is
     re-parsed and rejected on verbatim leakage, embedded code, or claims above
     the unlocked tier. Fails CLOSED: any exception is a rejection.

The order matters and is worth stating plainly: the strongest firewall is not
filtering the output, it is never supplying the input.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

# Fields that must never reach a prompt, at any tier, under any circumstance.
RESTRICTED = frozenset({
    "repair", "repair_patch", "reference_solution", "ablation_program",
    "killing_input_strategy", "fault_sig",
})

# What each tier is permitted to see. Views are built by explicit whitelist —
# never by copying a report and deleting keys, which fails open when a new
# restricted field is added later.
TIER_FIELDS: dict[int, tuple[str, ...]] = {
    0: ("concepts",),
    1: ("concepts", "fault_class", "spans"),
    2: ("concepts", "fault_class", "spans", "counterexample"),
    3: ("concepts", "fault_class", "spans", "counterexample", "complexity"),
}


class FirewallError(Exception):
    """Raised on any leak. Callers must treat this as a rejection, never
    as a reason to pass the text through."""


@dataclass(frozen=True)
class ContextView:
    tier: int
    data: dict

    def __post_init__(self):
        leaked = RESTRICTED & set(self.data)
        if leaked:
            raise FirewallError(f"restricted field(s) in view: {sorted(leaked)}")


def build_view(report: dict, tier: int) -> ContextView:
    """The Context Broker. Whitelist-only projection of a DiagnosticReport."""
    if tier not in TIER_FIELDS:
        raise FirewallError(f"unknown tier {tier}")
    allowed = TIER_FIELDS[tier]
    return ContextView(tier, {k: report[k] for k in allowed if k in report})


# --------------------------------------------------------------------------
# Output firewall
# --------------------------------------------------------------------------
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|\d+|<=|>=|==|!=|//|[<>+\-*/%\[\]().,:=]")


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text or "")


def forbidden_tokens(repair: Optional[dict], student_code: str) -> set[str]:
    """Tokens introduced ONLY by the fix.

    Takes STRUCTURED repair data ({"orig": "<=", "repl": "<"}), never a rendered
    label (BUILD_LOG F15). Tokenizing a human-readable description such as
    "L9: '<=' -> '<'" pulls in the formatting itself — the arrow's `-` and `>`,
    the `L9` — and those become spurious forbidden tokens that reject perfectly
    legitimate hints. The firewall must consume data, not prose.

    Only `repl` is forbidden. `orig` is what the student already wrote, so
    naming it is safe and often necessary for a useful hint.
    """
    student = set(tokens(student_code))
    if not repair:
        return set()

    # Two strengths, because punctuation and identifiers carry very different
    # leak signal (BUILD_LOG F17). Forbidding every token from every restricted
    # artifact re-blocks ordinary English: the `-` in "range-semantics" collides
    # with the `-` in a reference solution's `k-x`.
    strict: set[str] = set()   # the literal fix — forbid everything, incl. `<`
    loose: set[str] = set()    # other artifacts — identifiers / multi-char ops only

    if isinstance(repair, dict):
        strict |= set(tokens(repair.get("repl", "")))
        for k in ("reference_solution", "ablation_program", "killing_input_strategy"):
            if repair.get(k):
                loose |= {t for t in tokens(str(repair[k]))
                          if len(t) >= 2 and t.lower() not in PROSE_IDENTIFIERS}
    else:
        strict |= set(tokens(str(repair)))

    return (strict | loose) - student


# Identifiers in a reference solution that are ALSO ordinary English words.
# Banning these as tokens rejected legitimate prose: "store each value you have
# already SEEN" was blocked because the reference happens to name a variable
# `seen` (BUILD_LOG F27). A word like this is only a leak when it is used AS
# CODE, and `constructed_code` below is what decides that -- by structure, not
# by spelling.
PROSE_IDENTIFIERS = frozenset("""
seen total count counts sum value values from index result results left right
next last first min max key keys item items data size length order list set
map pair pairs start end current temp num nums number numbers array element
elements score target check store lookup found have same each been
""".split())

# A fragment is "code-like" if it contains BOTH an identifier and an operator or
# bracket. `k` alone is prose; `k - a[i]` is code.
_CODE_SHAPE = re.compile(r"[\[\]()+\-*/%<>=!]")
_IDENT = re.compile(r"[A-Za-z_]\w*")
# Unbackticked subscripts read as code wherever they appear: `seen[k - x]`.
_SUBSCRIPT = re.compile(r"\b[A-Za-z_]\w*\s*\[[^\]\n]{1,40}\]")
_BACKTICKED = re.compile(r"`([^`\n]{2,80})`")


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def constructed_code(hint: str, student_code: str) -> list[str]:
    """Code fragments in the hint that are NOT quotations of the student's source.

    This is the rule token filtering could not express. A model that has been
    told not to say `<` will happily write the reference algorithm in the
    STUDENT'S OWN identifiers -- "find the complement `k - a[i]`" leaks nothing
    the token filter recognises, because every token in it is already in the
    student's file. Measured: that exact string passed the firewall at tier 0
    (BUILD_LOG F27).

    The distinction that actually matters is not which tokens appear, but who
    wrote them:

        QUOTING the student back to themselves is legitimate and useful --
        "how does `i <= j` behave when i == j?" points at code they already have.

        CONSTRUCTING an expression they have NOT written is doing the work for
        them, whatever identifiers it happens to use.

    So: extract code-shaped fragments, normalise away whitespace, and reject any
    that does not already occur in the submission. Deterministic, language-
    agnostic, and it needs no model to adjudicate.
    """
    src = _squash(student_code)
    out: list[str] = []
    for frag in _BACKTICKED.findall(hint) + _SUBSCRIPT.findall(hint):
        if not (_CODE_SHAPE.search(frag) and _IDENT.search(frag)):
            continue                      # prose in backticks, e.g. `duplicates`
        if _squash(frag) not in src:
            out.append(frag.strip())
    return sorted(set(out))


def _contains_parsable_code(text: str, min_tokens: int = 4) -> bool:
    for line in text.splitlines():
        stripped = line.strip().strip("`").rstrip(".")
        if len(tokens(stripped)) < min_tokens:
            continue
        try:
            ast.parse(stripped)
            return True
        except SyntaxError:
            continue
    return False


@dataclass
class FirewallVerdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def screen(hint: str, tier: int, repair: Optional[dict] = None, student_code: str = "",
           counterexample: Optional[str] = None) -> FirewallVerdict:
    """Four mechanical layers. Any raise is a rejection (fail closed)."""
    reasons: list[str] = []
    try:
        # 1 — verbatim leakage of tokens the fix introduced
        if repair:
            bad = forbidden_tokens(repair, student_code)
            hit = sorted(bad & set(tokens(hint)))
            if hit:
                reasons.append(f"leaks repair token(s): {hit}")

        # 2 — embedded code
        if "```" in hint:
            reasons.append("contains a fenced code block")
        if _contains_parsable_code(hint):
            reasons.append("contains a parsable code statement")
        # 2b — code the student did not write. Quoting them back is fine;
        # composing new expressions for them is the leak (F27).
        made = constructed_code(hint, student_code)
        if made:
            reasons.append(f"constructs code the student has not written: {made}")

        # 3 — tier ceiling
        if tier < 1 and re.search(r"\bline\s+\d+|\bL\d+\b", hint, re.I):
            reasons.append("names a location above tier 0")
        if tier < 2 and counterexample and any(
                t in tokens(hint) for t in set(tokens(counterexample)) if t.isdigit()):
            reasons.append("reveals counterexample values above tier 1")

        # 4 — length sanity: a hint is a nudge, not a walkthrough
        if len(hint) > 600:
            reasons.append("exceeds hint length budget")
    except Exception as e:                       # fail CLOSED
        return FirewallVerdict(False, [f"firewall exception (rejected): {e!r}"])

    return FirewallVerdict(not reasons, reasons)


# --------------------------------------------------------------------------
# Generation seam
# --------------------------------------------------------------------------
Generator = Callable[[ContextView, list[str]], str]


def stub_generator(view: ContextView, prior_rejections: list[str]) -> str:
    """Deterministic, offline, zero-cost. Good enough to exercise the whole
    pipeline and to be driven adversarially by the red-team suite."""
    c = (view.data.get("concepts") or ["this concept"])[0]
    if view.tier == 0:
        return f"Revisit the idea of {c}. Something in your handling of it is off."
    if view.tier == 1:
        ln = (view.data.get("spans") or [{}])[0].get("line", "?")
        return (f"Look closely at line {ln}. The idea being tested there is {c}. "
                f"What exactly does that line claim, and is it always true?")
    if view.tier == 2:
        ce = view.data.get("counterexample", {})
        return (f"Consider this input: {ce.get('input', '(none)')}. Walk through your "
                f"code by hand on it. Where does your reasoning about {c} first "
                f"diverge from what you expected?")
    cx = view.data.get("complexity", {})
    return (f"Your solution measures {cx.get('measured', '?')} but the constraints "
            f"admit {cx.get('required', '?')}. The relevant idea is {c}: which "
            f"operation inside your loop costs more than you assumed?")


CANNED_FALLBACK = "Revisit the underlying concept and re-read your logic line by line."


@dataclass
class HintResult:
    text: str
    tier: int
    attempts: int
    rejections: list[str]
    fell_back: bool


def generate_hint(report: dict, tier: int, student_code: str,
                  generator: Generator = stub_generator,
                  max_attempts: int = 3) -> HintResult:
    """Build a tier view, generate, screen, retry on rejection, fall back to a
    canned concept-level hint rather than ever shipping a rejected one."""
    view = build_view(report, tier)          # raises if a restricted field leaks
    # Bundle every restricted code artifact for the token filter. Context
    # isolation already keeps these out of the prompt; this is defence in depth
    # against a model that GUESSES the fix rather than being told it.
    patch = dict(report.get("repair") or {})
    for k in ("reference_solution", "ablation_program", "killing_input_strategy"):
        if report.get(k):
            patch[k] = report[k]
    ce = (report.get("counterexample") or {}).get("input")

    rejections: list[str] = []
    for attempt in range(1, max_attempts + 1):
        try:
            hint = generator(view, rejections)
        except Exception as e:
            rejections.append(f"generator raised: {e!r}")
            continue
        verdict = screen(hint, tier, patch, student_code, ce)
        if verdict.ok:
            return HintResult(hint, tier, attempt, rejections, False)
        rejections.extend(verdict.reasons)

    return HintResult(CANNED_FALLBACK, tier, max_attempts, rejections, True)
