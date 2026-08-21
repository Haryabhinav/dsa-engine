import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    best = 0
    for i in range(n):
        z = 0
        for j in range(i, n):
            if a[j] == 0:
                z += 1
            if z <= k and j - i + 1 > best:
                best = j - i + 1
    print(best)

main()
