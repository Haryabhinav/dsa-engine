"""Seed the DSA concept DAG.

Authored by hand: 38 concepts. Deliberately includes two REDUNDANT edges to
exercise transitive reduction, so the hygiene pass has something real to catch.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "analysis"))
import knowledge as kn

C = [
    ("variables-loops",        "Loops and iteration"),
    ("arrays-indexing",        "Array indexing"),
    ("range-semantics",        "Inclusive vs exclusive ranges"),
    ("comparison-operators",   "Comparison operators"),
    ("integer-overflow",       "Integer width and overflow"),
    ("modular-arithmetic",     "Modular arithmetic"),

    ("loop-invariants",        "Loop invariants"),
    ("prefix-sums",            "Prefix sums"),
    ("two-pointers",           "Two pointers"),
    ("binary-search",          "Binary search"),
    ("sorting",                "Sorting"),
    ("comparator-semantics",   "Comparators and strict weak ordering"),
    ("hashing",                "Hashing"),
    ("hash-lookup",            "Hash-based lookup"),
    ("duplicate-handling",     "Handling duplicates"),
    ("pair-counting",          "Counting pairs"),
    ("container-complexity",   "Container operation costs"),
    ("asymptotic-analysis",    "Asymptotic analysis"),

    ("recursion",              "Recursion"),
    ("recursion-base-case",    "Recursion base cases"),
    ("divide-conquer",         "Divide and conquer"),
    ("merge-sort",             "Merge sort"),
    ("modular-exponentiation", "Modular exponentiation"),

    ("stacks",                 "Stacks"),
    ("queues",                 "Queues"),
    ("heaps",                  "Heaps"),
    ("priority-queue",         "Priority queues"),

    ("graph-representation",   "Graph representation"),
    ("bfs",                    "Breadth-first search"),
    ("dfs",                    "Depth-first search"),
    ("visited-marking",        "Visited marking"),
    ("shortest-path-unweighted", "Unweighted shortest paths"),
    ("dijkstra",               "Dijkstra's algorithm"),

    ("greedy-exchange",        "Greedy exchange arguments"),
    ("dp-state-definition",    "DP state definition"),
    ("dp-transitions",         "DP transitions"),
    ("memoization",            "Memoization"),
    ("dp-on-graphs",           "DP over graphs"),
]

E = [
    ("variables-loops", "loop-invariants"),
    ("range-semantics", "loop-invariants"),
    ("arrays-indexing", "prefix-sums"),
    ("loop-invariants", "two-pointers"),
    ("arrays-indexing", "two-pointers"),
    ("range-semantics", "binary-search"),
    ("loop-invariants", "binary-search"),
    ("comparison-operators", "binary-search"),
    ("comparison-operators", "sorting"),
    ("sorting", "comparator-semantics"),
    ("comparison-operators", "comparator-semantics"),
    ("arrays-indexing", "hashing"),
    ("hashing", "hash-lookup"),
    ("hash-lookup", "duplicate-handling"),
    ("hash-lookup", "pair-counting"),
    ("duplicate-handling", "pair-counting"),
    ("hash-lookup", "container-complexity"),
    ("arrays-indexing", "container-complexity"),
    ("container-complexity", "asymptotic-analysis"),

    ("variables-loops", "recursion"),
    ("recursion", "recursion-base-case"),
    ("recursion", "divide-conquer"),
    ("binary-search", "divide-conquer"),
    ("divide-conquer", "merge-sort"),
    ("sorting", "merge-sort"),
    ("modular-arithmetic", "modular-exponentiation"),
    ("divide-conquer", "modular-exponentiation"),
    ("integer-overflow", "modular-exponentiation"),

    ("arrays-indexing", "stacks"),
    ("arrays-indexing", "queues"),
    ("arrays-indexing", "heaps"),
    ("comparison-operators", "heaps"),
    ("heaps", "priority-queue"),

    ("arrays-indexing", "graph-representation"),
    ("hashing", "graph-representation"),
    ("queues", "bfs"),
    ("graph-representation", "bfs"),
    ("stacks", "dfs"),
    ("recursion", "dfs"),
    ("graph-representation", "dfs"),
    ("bfs", "visited-marking"),
    ("dfs", "visited-marking"),
    ("bfs", "shortest-path-unweighted"),
    ("priority-queue", "dijkstra"),
    ("graph-representation", "dijkstra"),
    ("visited-marking", "dijkstra"),
    ("shortest-path-unweighted", "dijkstra"),

    ("sorting", "greedy-exchange"),
    ("recursion", "dp-state-definition"),
    ("dp-state-definition", "dp-transitions"),
    ("recursion", "memoization"),
    ("hash-lookup", "memoization"),
    ("dp-transitions", "dp-on-graphs"),
    ("graph-representation", "dp-on-graphs"),

    # --- deliberately REDUNDANT: implied by longer paths -------------------
    ("arrays-indexing", "dijkstra"),          # via graph-representation
    ("variables-loops", "binary-search"),     # via loop-invariants
]

# fault signature -> concept  (produced by mutate.py's operator catalog)
F = [
    ("cmp:<=->:<",   "range-semantics"),
    ("cmp:<->:<=",   "range-semantics"),
    ("cmp:>=->:>",   "range-semantics"),
    ("cmp:==->:!=",  "comparator-semantics"),
    ("const:off1",   "loop-invariants"),
    ("bin:+->:-",    "prefix-sums"),
    ("bool:and->:or", "loop-invariants"),
    ("dup:double-count", "duplicate-handling"),
]

db = ROOT / "knowledge.db"
con = kn.connect(db)
con.execute("DELETE FROM concept"); con.execute("DELETE FROM concept_edge")
con.execute("DELETE FROM fault_signature")
for cid, name in C:
    con.execute("INSERT INTO concept (id, name) VALUES (?,?)", (cid, name))
for pa, ch in E:
    con.upsert("concept_edge", ["parent", "child", "kind"],
               {"parent": pa, "child": ch, "kind": "PREREQUISITE_OF", "approved": 1})
for sig, cid in F:
    con.upsert("fault_signature", ["sig"], {"sig": sig, "concept": cid})
con.commit()

stats = kn.rebuild_graph(con)
print(f"db: {db}")
print(f"  concepts        {stats['nodes']}")
print(f"  edges           {stats['edges']}")
print(f"  redundant       {stats['redundant']}  (marked, excluded from propagation)")
print(f"  nodes in cycles {stats['in_cycles']}")
red = con.execute("SELECT parent, child FROM concept_edge WHERE redundant=1").fetchall()
for r in red:
    print(f"    pruned: {r['parent']} -> {r['child']}")
closure = con.execute("SELECT COUNT(*) c FROM concept_closure").fetchone()["c"]
print(f"  closure rows    {closure}")
