import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    if n == 0 or k < 1 or k > n:
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
