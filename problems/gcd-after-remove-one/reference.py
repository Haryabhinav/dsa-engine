import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    from math import gcd
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
