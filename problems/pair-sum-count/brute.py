import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    total = 0
    for i in range(n):
        for j in range(i + 1, n):
            if a[i] + a[j] == k:
                total += 1
    print(total)

main()
