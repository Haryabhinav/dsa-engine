import sys

def sort_count(a):
    if len(a) <= 1:
        return a, 0
    m = len(a) // 2
    l, cl = sort_count(a[:m]); r, cr = sort_count(a[m:])
    out, i, j, c = [], 0, 0, cl + cr
    while i < len(l) and j < len(r):
        if l[i] <= r[j]:
            out.append(l[i]); i += 1
        else:
            out.append(r[j]); j += 1; c += len(l) - i
    out += l[i:] + r[j:]
    return out, c

def main():
    d = sys.stdin.read().split()
    n = int(d[0]); a = list(map(int, d[1:1 + n]))
    print(sort_count(a)[1])

main()
