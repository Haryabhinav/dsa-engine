"""C-family (C++) mutation front end — token level, an honest interim.

tree-sitter is the destination: a real CST makes structural guards expressible
("this comparison sits in a loop header"), which removes false sites. Until it is
installed this lexes the source with a tokenizer that skips strings and comments
and mutates operators in place.

Less precise than an AST — no structural guards — but sound in the way that
matters: every mutant is a real single-token edit at a real source offset, and
anything syntactically broken is rejected by a bracket-balance check or by the
compiler itself.
"""
from __future__ import annotations

import re

from mutate import Site

# Order matters: comments and strings are consumed first so operators inside
# them are never seen. `<<`/`>>` are matched before `<`/`>` and then discarded —
# flipping `cout << x` produces noise, not a candidate defect.
_CFAM = re.compile(
    r"""
      (?P<comment>//[^\n]*|/\*.*?\*/)
    | (?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
    | (?P<shift><<=|>>=|<<|>>)
    | (?P<incdec>\+\+|--)
    | (?P<op><=|>=|==|!=|&&|\|\||[<>])
    | (?P<num>\b\d+\b)
    """,
    re.X | re.S,
)

CFAM_MUT = {
    "<": ["<=", ">"],
    "<=": ["<", ">="],
    ">": [">=", "<"],
    ">=": [">", "<="],
    "==": ["!="],
    "!=": ["=="],
    "&&": ["||"],
    "||": ["&&"],
}

_CMP = {"<", "<=", ">", ">=", "==", "!="}


def _preprocessor_lines(src: str) -> set[int]:
    """`#include <iostream>` contains a `<` that is not a comparison. Token-level
    lexing cannot tell the difference, so preprocessor lines are excluded
    wholesale — a false site there costs a full compile for a guaranteed-useless
    mutant, and on C++ compilation is the dominant cost of the whole search."""
    return {i for i, ln in enumerate(src.splitlines(), 1)
            if ln.lstrip().startswith("#")}


def find_sites_cfamily(src: str) -> list[Site]:
    out: list[Site] = []
    skip = _preprocessor_lines(src)
    for m in _CFAM.finditer(src):
        kind = m.lastgroup
        if kind in ("comment", "string", "shift", "incdec"):
            continue
        text = m.group()
        line = src.count("\n", 0, m.start()) + 1
        if line in skip:
            continue
        # `vector<long long>` — an angle bracket glued to an identifier is
        # template syntax, not a comparison. Mutating it yields `vector<=long`,
        # which costs a full C++ compile to discover is garbage, and compilation
        # is the dominant cost of the whole search. A real comparison is
        # essentially always separated from its left operand.
        if text in ("<", ">", "<=", ">=") and m.start() > 0:
            prev = src[m.start() - 1]
            if prev.isalnum() or prev == "_":
                continue
        if kind == "op":
            for repl in CFAM_MUT.get(text, []):
                out.append(Site("cmp" if text in _CMP else "bool",
                                m.start(), m.end(), text, repl, line))
        elif kind == "num":
            v = int(text)
            for repl in sorted({str(v + 1), str(v - 1)}):
                out.append(Site("const", m.start(), m.end(), text, repl, line))
    return out


def balanced(src: str) -> bool:
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    for ch in src:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack
