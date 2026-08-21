import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    if n == 0 or k < 1 or k > n:
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
