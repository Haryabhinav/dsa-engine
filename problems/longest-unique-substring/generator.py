import argparse, random, sys
p = argparse.ArgumentParser(); p.add_argument("--seed", type=int, required=True)
p.add_argument("--n", type=int, required=True); a = p.parse_args()
rng = random.Random(a.seed)
alpha = "abcde"
s = "".join(rng.choice(alpha) for _ in range(a.n))
sys.stdout.write(f"{a.n}\n{s}\n" if a.n else "0\n\n")
