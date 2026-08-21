import argparse, random, sys
p = argparse.ArgumentParser(); p.add_argument("--seed", type=int, required=True)
p.add_argument("--n", type=int, required=True); a = p.parse_args()
rng = random.Random(a.seed)
# worst case for naive restart: long distinct runs punctuated by repeats
alpha = "abcdefghijklmnopqrstuvwxyz"
s = "".join(alpha[i % 26] for i in range(a.n))
if a.n > 3:
    s = s[:a.n // 2] + s[0] + s[a.n // 2 + 1:]
sys.stdout.write(f"{a.n}\n{s}\n" if a.n else "0\n\n")
