"""Two more problem bundles, chosen to exercise different parts of the engine.

  longest-unique-substring : two-pointer / sliding window. Required O(n).
                             Classic bug family = window-shrink off-by-one.
  count-inversions         : divide & conquer. Required O(n log n) — the case
                             the complexity fitter finds hardest to separate
                             from O(n), so it is a real test of the instrument.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

BUNDLES = {
"longest-unique-substring": {
 "meta": {
   "slug": "longest-unique-substring", "title": "Longest Substring Without Repeats",
   "statement": "Given a lowercase string, return the length of the longest substring with all distinct characters.",
   "n_max": 200000, "time_limit_ms": 2000, "ops_budget": 400000000,
   "required_complexity": "n", "solution_family": ["two-pointers", "hashing"],
   "concepts": [{"id": "two-pointers", "centrality": 0.9},
                {"id": "hash-lookup", "centrality": 0.6},
                {"id": "loop-invariants", "centrality": 0.7}],
   "edge_cases": ["empty", "single", "all_same", "all_distinct", "max_values"],
   "shrink_hint": {"kind": "string", "header_lines": 1},
 },
 "reference.py": '''import sys

def main():
    d = sys.stdin.read().split()
    n = int(d[0]); s = d[1] if len(d) > 1 else ""
    last = {}
    best = lo = 0
    for i, ch in enumerate(s):
        if ch in last and last[ch] >= lo:
            lo = last[ch] + 1
        last[ch] = i
        best = max(best, i - lo + 1)
    print(best)

main()
''',
 "brute.py": '''import sys

def main():
    d = sys.stdin.read().split()
    n = int(d[0]); s = d[1] if len(d) > 1 else ""
    best = 0
    for i in range(len(s)):
        seen = set()
        for j in range(i, len(s)):
            if s[j] in seen:
                break
            seen.add(s[j])
            best = max(best, j - i + 1)
    print(best)

main()
''',
 "generator.py": '''import argparse, random, sys
p = argparse.ArgumentParser(); p.add_argument("--seed", type=int, required=True)
p.add_argument("--n", type=int, required=True); a = p.parse_args()
rng = random.Random(a.seed)
alpha = "abcde"
s = "".join(rng.choice(alpha) for _ in range(a.n))
sys.stdout.write(f"{a.n}\\n{s}\\n" if a.n else "0\\n\\n")
''',
 "generator_adv.py": '''import argparse, random, sys
p = argparse.ArgumentParser(); p.add_argument("--seed", type=int, required=True)
p.add_argument("--n", type=int, required=True); a = p.parse_args()
rng = random.Random(a.seed)
# worst case for naive restart: long distinct runs punctuated by repeats
alpha = "abcdefghijklmnopqrstuvwxyz"
s = "".join(alpha[i % 26] for i in range(a.n))
if a.n > 3:
    s = s[:a.n // 2] + s[0] + s[a.n // 2 + 1:]
sys.stdout.write(f"{a.n}\\n{s}\\n" if a.n else "0\\n\\n")
''',
 "validator.py": '''import sys
d = sys.stdin.read().split()
if not d: sys.stderr.write("empty\\n"); sys.exit(1)
n = int(d[0]); s = d[1] if len(d) > 1 else ""
if len(s) != n: sys.stderr.write(f"len {len(s)} != n {n}\\n"); sys.exit(1)
if not (0 <= n <= 200000): sys.stderr.write("n range\\n"); sys.exit(1)
if any(not ch.islower() for ch in s): sys.stderr.write("non-lowercase\\n"); sys.exit(1)
sys.exit(0)
''',
 "samples": [("3\nabc\n", "3"), ("4\nabba\n", "2")],
},

"count-inversions": {
 "meta": {
   "slug": "count-inversions", "title": "Count Inversions",
   "statement": "Count pairs (i<j) with a[i] > a[j].",
   "n_max": 100000, "time_limit_ms": 2000, "ops_budget": 400000000,
   "required_complexity": "n log n", "solution_family": ["divide-conquer", "merge-sort"],
   "concepts": [{"id": "merge-sort", "centrality": 0.9},
                {"id": "divide-conquer", "centrality": 0.8},
                {"id": "comparison-operators", "centrality": 0.5}],
   "edge_cases": ["empty", "single", "sorted", "reverse_sorted", "all_same"],
   "shrink_hint": {"kind": "int_array", "header_lines": 1},
 },
 "reference.py": '''import sys

def sort_count(a):
    if len(a) <= 1:
        return a, 0
    m = len(a) // 2
    l, cl = sort_count(a[:m]); r, cr = sort_count(a[m:])
    out, i, j, c = [], 0, 0, cl + cr
    while i < len(l) and j < len(r):
        if l[i] <= r[j]:
            out.append(l[i]); i += 1
        else:
            out.append(r[j]); j += 1; c += len(l) - i
    out += l[i:] + r[j:]
    return out, c

def main():
    d = sys.stdin.read().split()
    n = int(d[0]); a = list(map(int, d[1:1 + n]))
    print(sort_count(a)[1])

main()
''',
 "brute.py": '''import sys

def main():
    d = sys.stdin.read().split()
    n = int(d[0]); a = list(map(int, d[1:1 + n]))
    c = 0
    for i in range(n):
        for j in range(i + 1, n):
            if a[i] > a[j]:
                c += 1
    print(c)

main()
''',
 "generator.py": '''import argparse, random, sys
p = argparse.ArgumentParser(); p.add_argument("--seed", type=int, required=True)
p.add_argument("--n", type=int, required=True); a = p.parse_args()
rng = random.Random(a.seed)
v = [rng.randint(-10, 10) for _ in range(a.n)]
sys.stdout.write(f"{a.n}\\n" + " ".join(map(str, v)) + "\\n")
''',
 "generator_adv.py": '''import argparse, random, sys
p = argparse.ArgumentParser(); p.add_argument("--seed", type=int, required=True)
p.add_argument("--n", type=int, required=True); a = p.parse_args()
# reverse-sorted maximises inversions: the worst case for any counting approach
v = list(range(a.n, 0, -1))
sys.stdout.write(f"{a.n}\\n" + " ".join(map(str, v)) + "\\n")
''',
 "validator.py": '''import sys
d = sys.stdin.read().split()
if not d: sys.stderr.write("empty\\n"); sys.exit(1)
n = int(d[0]); a = d[1:]
if len(a) != n: sys.stderr.write(f"expected {n} got {len(a)}\\n"); sys.exit(1)
if not (0 <= n <= 100000): sys.stderr.write("n range\\n"); sys.exit(1)
if any(abs(int(x)) > 10 ** 9 for x in a): sys.stderr.write("value range\\n"); sys.exit(1)
sys.exit(0)
''',
 "samples": [("4\n2 4 1 3\n", "3"), ("3\n1 2 3\n", "0")],
},
}

for slug, b in BUNDLES.items():
    d = ROOT / "problems" / slug
    (d / "samples").mkdir(parents=True, exist_ok=True)
    (d / "problem.json").write_text(json.dumps(b["meta"], indent=2), encoding="utf-8")
    for name in ("reference.py", "brute.py", "generator.py", "generator_adv.py", "validator.py"):
        (d / name).write_text(b[name], encoding="utf-8")
    for i, (inp, out) in enumerate(b["samples"], 1):
        (d / "samples" / f"{i:02d}.in").write_text(inp, encoding="utf-8")
        (d / "samples" / f"{i:02d}.out").write_text(out + "\n", encoding="utf-8")
    print("wrote", d.relative_to(ROOT))
