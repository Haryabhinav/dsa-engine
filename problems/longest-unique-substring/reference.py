import sys

def main():
    d = sys.stdin.read().split()
    n = int(d[0]); s = d[1] if len(d) > 1 else ""
    last = {}
    best = lo = 0
    for i, ch in enumerate(s):
        if ch in last and last[ch] >= lo:
            lo = last[ch] + 1
        last[ch] = i
        best = max(best, i - lo + 1)
    print(best)

main()
