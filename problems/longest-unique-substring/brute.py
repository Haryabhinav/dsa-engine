import sys

def main():
    d = sys.stdin.read().split()
    n = int(d[0]); s = d[1] if len(d) > 1 else ""
    best = 0
    for i in range(len(s)):
        seen = set()
        for j in range(i, len(s)):
            if s[j] in seen:
                break
            seen.add(s[j])
            best = max(best, j - i + 1)
    print(best)

main()
