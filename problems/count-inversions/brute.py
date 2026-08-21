import sys

def main():
    d = sys.stdin.read().split()
    n = int(d[0]); a = list(map(int, d[1:1 + n]))
    c = 0
    for i in range(n):
        for j in range(i + 1, n):
            if a[i] > a[j]:
                c += 1
    print(c)

main()
