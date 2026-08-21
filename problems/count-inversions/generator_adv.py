import argparse, random, sys
p = argparse.ArgumentParser(); p.add_argument("--seed", type=int, required=True)
p.add_argument("--n", type=int, required=True); a = p.parse_args()
# reverse-sorted maximises inversions: the worst case for any counting approach
v = list(range(a.n, 0, -1))
sys.stdout.write(f"{a.n}\n" + " ".join(map(str, v)) + "\n")
