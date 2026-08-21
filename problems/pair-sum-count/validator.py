import sys

d = sys.stdin.read().split()
if len(d) < 2:
    sys.stderr.write("missing header\n"); sys.exit(1)
n, k = int(d[0]), int(d[1])
a = d[2:]
if len(a) != n:
    sys.stderr.write(f"expected {n} values, got {len(a)}\n"); sys.exit(1)
if not (0 <= n <= 200000):
    sys.stderr.write("n out of range\n"); sys.exit(1)
if any(abs(int(x)) > 10 ** 9 for x in a):
    sys.stderr.write("value out of range\n"); sys.exit(1)
sys.exit(0)
