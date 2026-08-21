import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    if n == 0:
        print(0); return
    lo, hi = min(a), max(a)            # try every candidate target
    print(min(sum(abs(x - t) for x in a) for t in range(lo, hi + 1)))

main()
