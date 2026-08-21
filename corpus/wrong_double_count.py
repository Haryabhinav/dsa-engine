import sys
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
