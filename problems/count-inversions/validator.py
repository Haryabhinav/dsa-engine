import sys
d = sys.stdin.read().split()
if not d: sys.stderr.write("empty\n"); sys.exit(1)
n = int(d[0]); a = d[1:]
if len(a) != n: sys.stderr.write(f"expected {n} got {len(a)}\n"); sys.exit(1)
if not (0 <= n <= 100000): sys.stderr.write("n range\n"); sys.exit(1)
if any(abs(int(x)) > 10 ** 9 for x in a): sys.stderr.write("value range\n"); sys.exit(1)
sys.exit(0)
