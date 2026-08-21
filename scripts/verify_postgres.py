"""Prove the Postgres path end to end. Requires a running database.

    docker compose up -d postgres
    export DSA_DATABASE_URL=postgresql://dsa:dsa@localhost:5432/dsa
    python scripts/verify_postgres.py

Until this passes, the Postgres dialect is WRITTEN but UNVERIFIED and the README
says so. Generated SQL is inspectable without a server via store.preview_sql().
"""
import os, pathlib, sys, time
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "analysis"))
import knowledge as kn, store

dsn = os.environ.get("DSA_DATABASE_URL")
if not dsn:
    print("DSA_DATABASE_URL not set — cannot verify the Postgres path.")
    print("  docker compose up -d postgres")
    print("  export DSA_DATABASE_URL=postgresql://dsa:dsa@localhost:5432/dsa")
    sys.exit(2)

con = kn.connect(dsn=dsn)
assert con.dialect == store.POSTGRES, con.dialect
print(f"  connected, dialect={con.dialect}")

for t in ("mastery", "review_event", "concept_closure", "concept_edge",
          "fault_signature", "concept"):
    con.execute(f"DELETE FROM {t}")
con.commit()

con.execute("INSERT INTO concept (id, name) VALUES (?,?)", ("a", "A"))
con.execute("INSERT INTO concept (id, name) VALUES (?,?)", ("b", "B"))
con.upsert("concept_edge", ["parent", "child", "kind"],
           {"parent": "a", "child": "b", "kind": "PREREQUISITE_OF", "approved": 1})
con.commit()
print("  placeholders + upsert          OK")

stats = kn.rebuild_graph(con)
print(f"  graph rebuild (closure upsert) OK  {stats}")

now = time.time()
kn.record(con, "s1", "a", ok=False, now=now)
kn.record(con, "s1", "a", ok=True, now=now)          # exercises DO UPDATE
m = con.execute("SELECT * FROM mastery WHERE student=? AND concept=?", ("s1", "a")).fetchone()
assert m and m["seen"] == 1, m
print(f"  mastery upsert                 OK  stability={m['stability']:.2f}")

n = con.execute("SELECT COUNT(*) AS c FROM review_event").fetchone()["c"]
assert n == 2, n
print(f"  IDENTITY column                OK  {n} review events")

r = kn.retrievability(con, "s1", now)
q = kn.review_queue(con, "s1", now, limit=2)
print(f"  retrievability + queue         OK  {len(r.eff)} concepts, {len(q)} candidates")
con.close()
print("\n  POSTGRES PATH VERIFIED")
