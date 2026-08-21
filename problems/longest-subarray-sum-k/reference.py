import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    first = {0: 0}
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
