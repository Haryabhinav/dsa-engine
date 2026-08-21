import argparse, random, sys
p = argparse.ArgumentParser(); p.add_argument("--seed", type=int, required=True)
p.add_argument("--n", type=int, required=True); a = p.parse_args()
rng = random.Random(a.seed)
v = [rng.randint(-10, 10) for _ in range(a.n)]
sys.stdout.write(f"{a.n}\n" + " ".join(map(str, v)) + "\n")
