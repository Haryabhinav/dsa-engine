import sys

def main():
    d = sys.stdin.read().split()
    n, k = int(d[0]), int(d[1])
    a = list(map(int, d[2:2 + n]))
    if k > n or k < 1:
        print(0); return
    rest = list(a)
    out = 0
    for _ in range(k):                 # repeated minimum extraction
        m = min(rest)
        rest.remove(m)
        out = m
    print(out)

main()
