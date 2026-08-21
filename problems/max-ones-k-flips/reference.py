import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    left = 0
    zeros = 0
    best = 0
    for right in range(n):
        if a[right] == 0:
            zeros += 1
        while zeros > k:
            if a[left] == 0:
                zeros -= 1
            left += 1
        if right - left + 1 > best:
            best = right - left + 1
    print(best)

main()
