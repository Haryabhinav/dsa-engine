import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    if n < k or k < 1:
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
