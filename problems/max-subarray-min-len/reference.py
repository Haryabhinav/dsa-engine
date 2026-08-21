import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    if n < k or k < 1:
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
