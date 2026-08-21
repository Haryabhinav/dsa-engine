import argparse, random, sys

p = argparse.ArgumentParser()
p.add_argument("--seed", type=int, required=True)
p.add_argument("--n", type=int, required=True)
a = p.parse_args()
rng = random.Random(a.seed)

n = a.n
half = rng.randint(1, 5)
k = 2 * half
vals = [half] * n
for _ in range(max(1, n // 50)):
    vals[rng.randrange(n)] = rng.randint(-10, 10)
sys.stdout.write(f"{n} {k}\n" + " ".join(map(str, vals)) + "\n")
