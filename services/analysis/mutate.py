"""AST mutation engine — DSA-specific operator catalog, byte-range splicing.

Design note: we mutate by splicing byte ranges on the parsed tree, never by
regenerating source from an AST. Regeneration needs a correct pretty-printer per
language (formatting drift, comment loss) and is where cross-language mutation
systems die. Splicing keeps the mutant byte-identical everywhere except the
site, which also makes the repair patch trivial to extract.

Python uses the stdlib `ast` (it carries end positions). tree-sitter replaces
this module wholesale when a real CST is available — same Site interface,
same splicer.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass

# --- DSA-specific operator catalog ----------------------------------------
# Generic mutation operators are weak here. These are the shapes competitive
# programming solutions actually break on.
CMP = {
    "<":  ["<=", ">"],          # inclusive/exclusive bounds, direction
    "<=": ["<", ">="],
    ">":  [">=", "<"],
    ">=": [">", "<="],
    "==": ["!="],
    "!=": ["=="],
}
BIN = {
    "+": ["-"],
    "-": ["+"],
    "*": ["//"],
    "//": ["*"],
}
BOOL = {"and": ["or"], "or": ["and"]}

CMP_SYM = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=",
           ast.Eq: "==", ast.NotEq: "!="}
BIN_SYM = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.FloorDiv: "//"}


@dataclass(frozen=True)
class Site:
    kind: str          # cmp | bin | bool | const
    start: int         # absolute byte offset in source
    end: int
    orig: str
    repl: str
    line: int

    @property
    def label(self) -> str:
        return f"L{self.line}: {self.orig!r} -> {self.repl!r}  [{self.kind}]"

    @property
    def sig(self) -> str:
        """Stable key into the fault_signature table -> concept mapping.
        This is the bridge from Bisect into Halflife."""
        return f"{self.kind}:{self.orig}->:{self.repl}"


def _line_offsets(src: str) -> list[int]:
    offs, pos = [0], 0
    for ln in src.splitlines(keepends=True):
        pos += len(ln)
        offs.append(pos)
    return offs


def _abs(offs: list[int], line: int, col: int) -> int:
    return offs[line - 1] + col


def find_sites(src: str) -> list[Site]:
    """Every single-token mutation the catalog can apply to this source."""
    tree = ast.parse(src)
    offs = _line_offsets(src)
    out: list[Site] = []

    def op_span(a_end_ln, a_end_col, b_ln, b_col, sym):
        """Locate an infix operator's exact range between two operands."""
        a = _abs(offs, a_end_ln, a_end_col)
        b = _abs(offs, b_ln, b_col)
        seg = src[a:b]
        i = seg.find(sym)
        return (a + i, a + i + len(sym)) if i >= 0 else None

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            sym = CMP_SYM.get(type(node.ops[0]))
            if not sym:
                continue
            r = node.comparators[0]
            span = op_span(node.left.end_lineno, node.left.end_col_offset,
                           r.lineno, r.col_offset, sym)
            if span:
                for repl in CMP.get(sym, []):
                    out.append(Site("cmp", span[0], span[1], sym, repl, node.lineno))

        elif isinstance(node, ast.BinOp):
            sym = BIN_SYM.get(type(node.op))
            if not sym:
                continue
            span = op_span(node.left.end_lineno, node.left.end_col_offset,
                           node.right.lineno, node.right.col_offset, sym)
            if span:
                for repl in BIN.get(sym, []):
                    out.append(Site("bin", span[0], span[1], sym, repl, node.lineno))

        elif isinstance(node, ast.BoolOp) and len(node.values) >= 2:
            sym = "and" if isinstance(node.op, ast.And) else "or"
            span = op_span(node.values[0].end_lineno, node.values[0].end_col_offset,
                           node.values[1].lineno, node.values[1].col_offset, sym)
            if span:
                for repl in BOOL[sym]:
                    out.append(Site("bool", span[0], span[1], sym, repl, node.lineno))

        elif (isinstance(node, ast.Constant) and isinstance(node.value, int)
              and not isinstance(node.value, bool) and node.end_lineno is not None):
            s = _abs(offs, node.lineno, node.col_offset)
            e = _abs(offs, node.end_lineno, node.end_col_offset)
            if src[s:e].lstrip("-").isdigit():
                for repl in {str(node.value + 1), str(node.value - 1)}:
                    out.append(Site("const", s, e, src[s:e], repl, node.lineno))

    # dedupe identical (span, repl) pairs, keep a stable order
    seen, uniq = set(), []
    for s in out:
        key = (s.start, s.end, s.repl)
        if key not in seen and s.orig != s.repl:
            seen.add(key)
            uniq.append(s)
    return uniq


def apply(src: str, site: Site) -> str | None:
    """Splice one site. Returns None if the result is not valid Python."""
    out = src[:site.start] + site.repl + src[site.end:]
    try:
        ast.parse(out)
    except SyntaxError:
        return None
    return out

