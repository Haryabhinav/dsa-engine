import sys
d = sys.stdin.read().split()
if not d: sys.stderr.write("empty\n"); sys.exit(1)
n = int(d[0]); s = d[1] if len(d) > 1 else ""
if len(s) != n: sys.stderr.write(f"len {len(s)} != n {n}\n"); sys.exit(1)
if not (0 <= n <= 200000): sys.stderr.write("n range\n"); sys.exit(1)
if any(not ch.islower() for ch in s): sys.stderr.write("non-lowercase\n"); sys.exit(1)
sys.exit(0)
