import sys
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
