"""Author problem bundles for the R1 experiment.

The problem SET is chosen to mirror the real Codeforces beginner-band tag
distribution measured from their API (11,363 problems; 3,682 rated <=1400; top
tags implementation / greedy / math / sortings / strings / dp / binary search /
two pointers). The problems themselves are written here, because Codeforces
exposes neither statements nor submission source through its API and its pages
sit behind bot protection.

Every bundle keeps the same I/O shape -- `n k` then n integers -- so the typed
int_array shrinker (Test 42) applies unchanged across all of them.

Every reference and brute pair is a DIFFERENT ALGORITHM, per PROBLEM_CONTRACT:
if brute were just a slower spelling of reference, the oracle gate would agree
with itself and prove nothing.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "problems"

GEN = '''import argparse, random, sys
p = argparse.ArgumentParser()
p.add_argument("--seed", type=int, required=True)
p.add_argument("--n", type=int, required=True)
a = p.parse_args()
rng = random.Random(a.seed)
n = a.n
{body}
sys.stdout.write(f"{{n}} {{k}}\\n" + " ".join(map(str, vals)) + "\\n")
'''

VAL = '''import sys
d = sys.stdin.read().split()
if len(d) < 2:
    sys.stderr.write("missing header\\n"); sys.exit(1)
n, k = int(d[0]), int(d[1])
a = d[2:]
if len(a) != n:
    sys.stderr.write(f"expected {{n}} values, got {{len(a)}}\\n"); sys.exit(1)
if not (0 <= n <= {nmax}):
    sys.stderr.write("n out of range\\n"); sys.exit(1)
{extra}
sys.exit(0)
'''

READ = '''import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
'''

P = {}

# ---------------------------------------------------------------- 1. dp / prefix
P["max-subarray-min-len"] = dict(
    title="Maximum Sum of a Subarray of Length at Least K",
    statement="Given n integers and k, find the maximum sum over all contiguous subarrays of length at least k.",
    required="n", nmax=200000, tags=["dp", "prefix sums", "implementation"],
    concepts=[("prefix-sums", 0.9), ("loop-invariants", 0.6), ("dp-state-definition", 0.5)],
    gen='k = rng.randint(1, max(1, n))\nvals = [rng.randint(-20, 20) for _ in range(n)]',
    ref=READ + '''    if n < k or k < 1:
        print(0); return
    pre = [0] * (n + 1)
    for i, x in enumerate(a):
        pre[i + 1] = pre[i] + x
    best = pre[k] - pre[0]
    lo = 0
    for r in range(k, n + 1):
        if pre[r - k] < pre[lo]:
            lo = r - k
        if pre[r] - pre[lo] > best:
            best = pre[r] - pre[lo]
    print(best)

main()
''',
    brute=READ + '''    if n < k or k < 1:
        print(0); return
    best = None
    for i in range(n):
        s = 0
        for j in range(i, n):
            s += a[j]
            if j - i + 1 >= k and (best is None or s > best):
                best = s
    print(best if best is not None else 0)

main()
''',
    samples=[("5 2\\n1 -2 3 4 -1\\n", "7"), ("3 3\\n-1 -2 -3\\n", "-6")])

# ---------------------------------------------------------------- 2. sortings
P["kth-smallest"] = dict(
    title="K-th Smallest Element",
    statement="Given n integers and k, output the k-th smallest value (1-indexed). If k>n output 0.",
    required="n log n", nmax=200000, tags=["sortings", "implementation"],
    concepts=[("sorting", 0.9), ("comparison-operators", 0.5), ("arrays-indexing", 0.5)],
    gen='k = rng.randint(1, max(1, n))\nvals = [rng.randint(-50, 50) for _ in range(n)]',
    ref=READ + '''    if k > n or k < 1:
        print(0); return
    print(sorted(a)[k - 1])

main()
''',
    brute=READ + '''    if k > n or k < 1:
        print(0); return
    rest = list(a)
    out = 0
    for _ in range(k):                 # repeated minimum extraction
        m = min(rest)
        rest.remove(m)
        out = m
    print(out)

main()
''',
    samples=[("5 2\\n5 1 4 2 3\\n", "2"), ("3 1\\n7 7 7\\n", "7")])

# ---------------------------------------------------------------- 3. hashing
P["longest-subarray-sum-k"] = dict(
    title="Longest Subarray With Sum Exactly K",
    statement="Given n integers and k, output the length of the longest contiguous subarray whose sum is exactly k, or 0.",
    required="n", nmax=200000, tags=["data structures", "prefix sums", "implementation"],
    concepts=[("prefix-sums", 0.9), ("hash-lookup", 0.8), ("loop-invariants", 0.5)],
    gen='k = rng.randint(-15, 15)\nvals = [rng.randint(-6, 6) for _ in range(n)]',
    ref=READ + '''    first = {0: 0}
    s = 0
    best = 0
    for i, x in enumerate(a, 1):
        s += x
        if s - k in first and i - first[s - k] > best:
            best = i - first[s - k]
        if s not in first:
            first[s] = i
    print(best)

main()
''',
    brute=READ + '''    best = 0
    for i in range(n):
        s = 0
        for j in range(i, n):
            s += a[j]
            if s == k and j - i + 1 > best:
                best = j - i + 1
    print(best)

main()
''',
    samples=[("5 3\\n1 2 3 -3 3\\n", "4"), ("3 10\\n1 2 3\\n", "0")])

# ---------------------------------------------------------------- 4. two pointers
P["max-ones-k-flips"] = dict(
    title="Longest Run of Ones After K Flips",
    statement="Given n values each 0 or 1 and k, output the length of the longest contiguous run of ones achievable by flipping at most k zeros.",
    required="n", nmax=200000, tags=["two pointers", "greedy", "implementation"],
    concepts=[("two-pointers", 0.9), ("loop-invariants", 0.7), ("range-semantics", 0.6)],
    gen='k = rng.randint(0, 4)\nvals = [rng.randint(0, 1) for _ in range(n)]',
    ref=READ + '''    left = 0
    zeros = 0
    best = 0
    for right in range(n):
        if a[right] == 0:
            zeros += 1
        while zeros > k:
            if a[left] == 0:
                zeros -= 1
            left += 1
        if right - left + 1 > best:
            best = right - left + 1
    print(best)

main()
''',
    brute=READ + '''    best = 0
    for i in range(n):
        z = 0
        for j in range(i, n):
            if a[j] == 0:
                z += 1
            if z <= k and j - i + 1 > best:
                best = j - i + 1
    print(best)

main()
''',
    samples=[("6 1\\n1 0 1 1 0 1\\n", "4"), ("4 0\\n0 0 0 0\\n", "0")])

# ---------------------------------------------------------------- 5. number theory
P["gcd-after-remove-one"] = dict(
    title="Best GCD After Removing One Element",
    statement="Given n positive integers (k is ignored), output the maximum possible gcd of the array after deleting exactly one element.",
    required="n", nmax=200000, tags=["number theory", "math", "implementation"],
    concepts=[("modular-arithmetic", 0.6), ("prefix-sums", 0.5), ("arrays-indexing", 0.5)],
    gen='k = 0\nvals = [rng.choice([2,3,4,6,8,12,24,36]) * rng.randint(1, 4) for _ in range(n)]',
    ref=READ + '''    from math import gcd
    if n <= 1:
        print(0); return
    pre = [0] * (n + 1)
    suf = [0] * (n + 1)
    for i in range(n):
        pre[i + 1] = gcd(pre[i], a[i])
    for i in range(n - 1, -1, -1):
        suf[i] = gcd(suf[i + 1], a[i])
    print(max(gcd(pre[i], suf[i + 1]) for i in range(n)))

main()
''',
    brute=READ + '''    from math import gcd
    if n <= 1:
        print(0); return
    best = 0
    for skip in range(n):              # recompute from scratch each time
        g = 0
        for i in range(n):
            if i != skip:
                g = gcd(g, a[i])
        if g > best:
            best = g
    print(best)

main()
''',
    samples=[("3 0\\n4 8 3\\n", "4"), ("2 0\\n5 7\\n", "7")])

# ---------------------------------------------------------------- 6. greedy
P["min-moves-equalize"] = dict(
    title="Minimum Moves to Equalize",
    statement="Given n integers (k is ignored), output the minimum total number of unit increments/decrements needed to make all values equal.",
    required="n log n", nmax=200000, tags=["greedy", "sortings", "math"],
    concepts=[("sorting", 0.8), ("greedy-exchange", 0.8), ("arrays-indexing", 0.4)],
    gen='k = 0\nvals = [rng.randint(-30, 30) for _ in range(n)]',
    ref=READ + '''    if n == 0:
        print(0); return
    b = sorted(a)
    med = b[n // 2]
    print(sum(abs(x - med) for x in b))

main()
''',
    brute=READ + '''    if n == 0:
        print(0); return
    lo, hi = min(a), max(a)            # try every candidate target
    print(min(sum(abs(x - t) for x in a) for t in range(lo, hi + 1)))

main()
''',
    samples=[("3 0\\n1 2 3\\n", "2"), ("4 0\\n1 1 1 1\\n", "0")])

# ---------------------------------------------------------------- 7. binary search
P["min-max-partition-sum"] = dict(
    title="Split Array Into K Parts Minimising the Largest Sum",
    statement="Given n non-negative integers and k, split into exactly k contiguous non-empty parts minimising the largest part sum.",
    required="n log n", nmax=100000, tags=["binary search", "greedy", "dp"],
    concepts=[("binary-search", 0.9), ("greedy-exchange", 0.7), ("prefix-sums", 0.5)],
    gen='k = rng.randint(1, max(1, min(n, 5)))\nvals = [rng.randint(0, 20) for _ in range(n)]',
    ref=READ + '''    if n == 0 or k < 1 or k > n:
        print(0); return

    def parts_needed(cap):
        cnt, cur = 1, 0
        for x in a:
            if cur + x <= cap:
                cur += x
            else:
                cnt += 1
                cur = x
        return cnt

    lo, hi = max(a), sum(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if parts_needed(mid) <= k:
            hi = mid
        else:
            lo = mid + 1
    print(lo)

main()
''',
    brute=READ + '''    if n == 0 or k < 1 or k > n:
        print(0); return
    import functools
    sys.setrecursionlimit(10000)

    @functools.lru_cache(maxsize=None)
    def best(i, parts):                # exact DP, a different algorithm
        if parts == 1:
            return sum(a[i:])
        out = None
        s = 0
        for j in range(i, n - parts + 1):
            s += a[j]
            cand = max(s, best(j + 1, parts - 1))
            if out is None or cand < out:
                out = cand
        return out
    print(best(0, k))

main()
''',
    samples=[("5 2\\n7 2 5 10 8\\n", "18"), ("3 3\\n1 2 3\\n", "3")])


def write(slug, spec):
    d = OUT / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "problem.json").write_text(json.dumps({
        "slug": slug, "title": spec["title"], "statement": spec["statement"],
        "n_max": spec["nmax"], "time_limit_ms": 2000, "ops_budget": 400000000,
        "required_complexity": spec["required"],
        "solution_family": spec["tags"],
        "concepts": [{"id": c, "centrality": w} for c, w in spec["concepts"]],
        "edge_cases": ["empty", "single", "all_duplicates", "negatives", "max_values"],
        "shrink_hint": {"kind": "int_array", "header_lines": 1},
    }, indent=2), encoding="utf-8")
    (d / "generator.py").write_text(GEN.format(body=spec["gen"]), encoding="utf-8")
    (d / "generator_adv.py").write_text(GEN.format(body=spec["gen"]), encoding="utf-8")
    (d / "validator.py").write_text(VAL.format(nmax=spec["nmax"], extra=""), encoding="utf-8")
    (d / "reference.py").write_text(spec["ref"], encoding="utf-8")
    (d / "brute.py").write_text(spec["brute"], encoding="utf-8")
    s = d / "samples"
    s.mkdir(exist_ok=True)
    for i, (inp, out) in enumerate(spec["samples"], 1):
        (s / f"{i:02d}.in").write_text(inp.replace("\\n", "\n"), encoding="utf-8")
        (s / f"{i:02d}.out").write_text(out + "\n", encoding="utf-8")
    return d


if __name__ == "__main__":
    for slug, spec in P.items():
        d = write(slug, spec)
        print(f"  wrote {d.relative_to(ROOT)}")
    print(f"\n  {len(P)} bundles written")
