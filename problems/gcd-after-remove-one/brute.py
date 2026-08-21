import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    from math import gcd
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
