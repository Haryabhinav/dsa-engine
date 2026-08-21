import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    if n == 0:
        print(0); return
    b = sorted(a)
    med = b[n // 2]
    print(sum(abs(x - med) for x in b))

main()
