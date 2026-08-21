"""Writes the first problem bundle + a corpus of student submissions."""
import json, os, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
P = ROOT / "problems" / "pair-sum-count"
C = ROOT / "corpus"
(P / "samples").mkdir(parents=True, exist_ok=True)
C.mkdir(parents=True, exist_ok=True)

F = {}

F["problem.json"] = json.dumps({
    "slug": "pair-sum-count",
    "title": "Count Pairs With Given Sum",
    "statement": "Given n integers and a target k, count index pairs (i<j) with a[i]+a[j]==k.",
    "n_max": 200000,
    "time_limit_ms": 2000,
    "ops_budget": 400000000,
    "required_complexity": "n",
    "solution_family": ["hashing", "counting"],
    "concepts": [
        {"id": "hash-lookup", "centrality": 0.9},
        {"id": "pair-counting", "centrality": 0.6},
        {"id": "duplicate-handling", "centrality": 0.7},
    ],
    "edge_cases": ["empty", "single", "all_duplicates", "max_values", "negatives", "self_pair"],
    "shrink_hint": {"kind": "int_array", "header_lines": 1},
}, indent=2)

# --- trusted oracles -------------------------------------------------------
F["reference.py"] = '''import sys
from collections import Counter

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    seen, total = Counter(), 0
    for x in a:
        total += seen[k - x]
        seen[x] += 1
    print(total)

main()
'''

F["brute.py"] = '''import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    total = 0
    for i in range(n):
        for j in range(i + 1, n):
            if a[i] + a[j] == k:
                total += 1
    print(total)

main()
'''

F["generator.py"] = '''import argparse, random, sys

p = argparse.ArgumentParser()
p.add_argument("--seed", type=int, required=True)
p.add_argument("--n", type=int, required=True)
a = p.parse_args()
rng = random.Random(a.seed)

n = a.n
k = rng.randint(-20, 20)
vals = [rng.randint(-10, 10) for _ in range(n)]
sys.stdout.write(f"{n} {k}\\n" + " ".join(map(str, vals)) + "\\n")
'''

# worst case: everything collides on k/2 -> maximal pair count, maximal hash pressure
F["generator_adv.py"] = '''import argparse, random, sys

p = argparse.ArgumentParser()
p.add_argument("--seed", type=int, required=True)
p.add_argument("--n", type=int, required=True)
a = p.parse_args()
rng = random.Random(a.seed)

n = a.n
half = rng.randint(1, 5)
k = 2 * half
vals = [half] * n
for _ in range(max(1, n // 50)):
    vals[rng.randrange(n)] = rng.randint(-10, 10)
sys.stdout.write(f"{n} {k}\\n" + " ".join(map(str, vals)) + "\\n")
'''

F["validator.py"] = '''import sys

d = sys.stdin.read().split()
if len(d) < 2:
    sys.stderr.write("missing header\\n"); sys.exit(1)
n, k = int(d[0]), int(d[1])
a = d[2:]
if len(a) != n:
    sys.stderr.write(f"expected {n} values, got {len(a)}\\n"); sys.exit(1)
if not (0 <= n <= 200000):
    sys.stderr.write("n out of range\\n"); sys.exit(1)
if any(abs(int(x)) > 10 ** 9 for x in a):
    sys.stderr.write("value out of range\\n"); sys.exit(1)
sys.exit(0)
'''

for name, body in F.items():
    (P / name).write_text(body, encoding="utf-8")

(P / "samples" / "01.in").write_text("4 6\n1 5 3 3\n", encoding="utf-8")
(P / "samples" / "01.out").write_text("2\n", encoding="utf-8")
(P / "samples" / "02.in").write_text("2 4\n2 2\n", encoding="utf-8")
(P / "samples" / "02.out").write_text("1\n", encoding="utf-8")

# --- student corpus --------------------------------------------------------
# BUG: counts each pair twice and mishandles x == k-x (self-pairing)
(C / "wrong_double_count.py").write_text('''import sys
from collections import Counter

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    cnt = Counter(a)
    total = 0
    for x in a:
        total += cnt[k - x]
    print(total // 2)

main()
''', encoding="utf-8")

# CORRECT but quadratic -> should TLE / fit as n^2
(C / "correct_quadratic.py").write_text('''import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    total = 0
    for i in range(n):
        for j in range(i + 1, n):
            if a[i] + a[j] == k:
                total += 1
    print(total)

main()
''', encoding="utf-8")

# CORRECT and linear -> the good submission
(C / "correct_linear.py").write_text('''import sys
from collections import Counter

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    seen, total = Counter(), 0
    for x in a:
        total += seen[k - x]
        seen[x] += 1
    print(total)

main()
''', encoding="utf-8")

print("bundle:", P)
print("corpus:", C)
for f in sorted(P.rglob("*")):
    if f.is_file():
        print("  ", f.relative_to(ROOT))
for f in sorted(C.glob("*.py")):
    print("  ", f.relative_to(ROOT))
