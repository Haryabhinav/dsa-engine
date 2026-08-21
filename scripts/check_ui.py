"""Syntax-check the served frontend, and check that its wiring is present.

WHY THIS EXISTS. A `\\n` escape lost in a shell heredoc put a literal newline
inside a JS string literal. That is a parse error, so the ENTIRE <script> block
died -- including `$("#go").onclick = go` -- and the page rendered perfectly with
a Diagnose button that did nothing (BUILD_LOG F39).

Nothing caught it. The API was healthy and returned run ids on demand; `curl` of
the page returned 200 with the right bytes; every backend test passed. The only
observer that could have noticed was a browser, and browsers were not in the loop.

A frontend that parses is not a tested frontend, but a frontend that does NOT
parse is definitely a broken one, and that is cheap to know.

Run:  python scripts/check_ui.py
"""
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = ROOT / "services" / "gateway" / "static" / "index.html"
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Event bindings without which the page LOOKS fine and does nothing.
REQUIRED = [
    '$("#go").onclick',            # Diagnose
    '$("#preset").onchange',       # demo loader
    "EventSource(",                # cascade stream
    "/api/diagnose",
    "/api/hint",
    "/api/next",
    "/api/progress",
    'loadNext(', 'loadProgress(', '$("#student")',
    "drawRail(", "drawLadder(",
]


def main() -> int:
    html = HTML.read_text(encoding="utf-8")
    m = re.search(r"<script>(.*?)</script>", html, re.S)
    if not m:
        print("  FAIL  no <script> block found")
        return 1
    js = m.group(1)
    bad = 0

    node = shutil.which("node")
    if node:
        tmp = ROOT / ".scratch" / "ui_check.js"
        tmp.parent.mkdir(exist_ok=True)
        tmp.write_text(js, encoding="utf-8")
        cp = subprocess.run([node, "--check", str(tmp)], capture_output=True, text=True)
        ok = cp.returncode == 0
        print(f"  {'PASS' if ok else 'FAIL'}  javascript parses ({len(js)} chars)")
        if not ok:
            print("        " + (cp.stderr or "").strip()[:300])
            bad += 1
    else:
        # Fallback with no node: a literal newline inside a quoted string is
        # exactly what a mangled heredoc produces.
        lines = js.splitlines()
        susp = [i for i, l in enumerate(lines, 1)
                if "`" not in l and (l.count('"') % 2 or l.count("'") % 2)]
        print(f"  {'PASS' if not susp else 'FAIL'}  quote balance (node unavailable)")
        if susp:
            print(f"        unbalanced on lines {susp[:8]}")
            bad += 1

    for token in REQUIRED:
        present = token in js
        if not present:
            bad += 1
        print(f"  {'PASS' if present else 'FAIL'}  wiring present: {token}")

    print(f"\n  {'UI CHECK PASSED' if not bad else f'{bad} PROBLEM(S)'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
