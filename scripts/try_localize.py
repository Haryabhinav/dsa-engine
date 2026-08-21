import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "analysis"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from engine import Problem
import localize as bx

p = Problem.load(ROOT / "problems" / "pair-sum-count")

for name in ["wrong_selfpair.py", "wrong_double_count.py"]:
    sub = ROOT / "corpus" / name
    loc, fails, passes = bx.localize(p, sub)
    print(f"\n=== {name} ===")
    print(f"  suite: {len(fails)} failing, {len(passes)} passing")
    print(f"  mutation sites: {loc.total_sites} total, {loc.tried} tried after coverage pruning")
    print(f"  TIER: {loc.tier}")
    if loc.tier == "PROVEN":
        print(f"  minimal repair at line {loc.patch_line}   [RESTRICTED: {loc.patch}]")
    print("  top suspicious lines (Ochiai):")
    for ln, sc in loc.lines[:5]:
        print(f"    L{ln:<3} {sc:.3f}")
