import argparse, random, sys
p = argparse.ArgumentParser()
p.add_argument("--seed", type=int, required=True)
p.add_argument("--n", type=int, required=True)
a = p.parse_args()
rng = random.Random(a.seed)
n = a.n
k = 0
vals = [rng.randint(-30, 30) for _ in range(n)]
sys.stdout.write(f"{n} {k}\n" + " ".join(map(str, vals)) + "\n")
