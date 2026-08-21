"""Semantic layer — Qdrant + local embeddings.

The governing rule, and it is enforced in code rather than by convention:

    VECTORS SUGGEST. SQLITE DECIDES.

Nothing in this module writes to mastery, decays a concept, or maps a fault to a
concept on its own authority. Every result carries `requires_confirmation=True`
and is a *candidate* for a human or for an exact-match lookup to ratify. A
similarity score is evidence of resemblance, never evidence of identity, and the
whole engine's credibility rests on not confusing the two.

Deployment note: Qdrant runs in **local mode** here — `QdrantClient(path=…)`
persists to a directory, no server, no daemon, no container. Embeddings come from
`fastembed` (BAAI/bge-small-en-v1.5, 384-dim ONNX) which runs on the CPU with no
API key and no per-call cost. The model downloads once (~50 MB) on first use.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Iterable, Optional

from qdrant_client import QdrantClient, models

ROOT = pathlib.Path(__file__).resolve().parents[2]
STORE = ROOT / "qdrant_store"
MODEL = "BAAI/bge-small-en-v1.5"

CONCEPTS = "concepts"
PROBLEMS = "problems"
MISCONCEPTIONS = "misconceptions"


@dataclass
class Suggestion:
    id: str
    score: float
    payload: dict
    requires_confirmation: bool = True      # never defaults to False. Ever.


def client(in_memory: bool = False) -> QdrantClient:
    if in_memory:
        return QdrantClient(":memory:")
    STORE.mkdir(exist_ok=True)
    return QdrantClient(path=str(STORE))


def _ensure(qc: QdrantClient, name: str) -> None:
    if not qc.collection_exists(name):
        qc.create_collection(
            name,
            vectors_config=models.VectorParams(
                size=qc.get_embedding_size(MODEL), distance=models.Distance.COSINE),
        )


def _upsert(qc: QdrantClient, name: str, ids: list[int], docs: list[str],
            payloads: list[dict]) -> None:
    _ensure(qc, name)
    if not docs:
        return
    qc.upsert(name, points=models.Batch(
        ids=ids,
        vectors=[models.Document(text=d, model=MODEL) for d in docs],
        payloads=payloads,
    ))


# --------------------------------------------------------------------------
# Indexing
# --------------------------------------------------------------------------
def index_concepts(qc: QdrantClient, rows: Iterable[dict]) -> int:
    ids, docs, pays = [], [], []
    for i, r in enumerate(rows):
        # Embed name + description together: the slug alone ("hash-lookup") is
        # too terse to carry meaning, and the name alone loses the qualifiers.
        text = f"{r['name']}. {r.get('description') or r['name']}"
        ids.append(i); docs.append(text)
        pays.append({"concept_id": r["id"], "name": r["name"], "text": text})
    _upsert(qc, CONCEPTS, ids, docs, pays)
    return len(ids)


def index_problems(qc: QdrantClient, metas: Iterable[dict]) -> int:
    ids, docs, pays = [], [], []
    for i, m in enumerate(metas):
        text = f"{m.get('title','')}. {m.get('statement','')}"
        ids.append(i); docs.append(text)
        pays.append({"slug": m["slug"], "title": m.get("title", ""),
                     "required": m.get("required_complexity", ""), "text": text})
    _upsert(qc, PROBLEMS, ids, docs, pays)
    return len(ids)


def index_misconceptions(qc: QdrantClient, rows: Iterable[dict]) -> int:
    """Fault signatures described in prose, so an UNSEEN mutation delta can be
    matched by resemblance when no exact signature row exists."""
    ids, docs, pays = [], [], []
    for i, r in enumerate(rows):
        ids.append(i); docs.append(r["text"])
        pays.append({"sig": r["sig"], "concept_id": r["concept"], "text": r["text"]})
    _upsert(qc, MISCONCEPTIONS, ids, docs, pays)
    return len(ids)


# --------------------------------------------------------------------------
# Query — every path returns Suggestions, never decisions
# --------------------------------------------------------------------------
def _search(qc: QdrantClient, name: str, text: str, k: int,
            floor: float, margin: float = 0.02) -> list[Suggestion]:
    """Two gates, and the second is the one that matters.

    FLOOR (absolute): cosine always returns a nearest neighbour, so without an
    absolute threshold an unrelated query still yields a confident-looking
    answer. "What is the best recipe for sourdough bread?" would name a DSA
    concept.

    MARGIN (relative): a cheap guard against a pathological tie, kept low.

    A NOTE ON WHAT DID NOT WORK (BUILD_LOG F22). The margin was first introduced
    as the *primary* discriminator, by analogy with F5 (every model R^2 ~ 1.000)
    and F8 (every Ochiai score tied) -- the same "confident ranking, no signal"
    shape. Measured against labelled queries, that analogy is FALSE here:

        want   top     2nd    margin   query
        GOOD   0.779   0.735   0.044   shortest route between two cities
        BAD    0.655   0.604   0.051   longest run of distinct characters
        GOOD   0.875   0.743   0.132   extract the smallest pending item
        BAD    0.464   0.454   0.009   best recipe for sourdough bread

    The good case has a SMALLER margin than the bad one. No margin threshold
    separates them. Absolute score does: genuine hits sit at 0.77+ while
    unanswerable queries top out around 0.66. So the FLOOR is the discriminator
    and the margin is only a tie-breaker. Tuned against measurement, not analogy.
    """
    if not qc.collection_exists(name):
        return []
    res = qc.query_points(name, query=models.Document(text=text, model=MODEL),
                          limit=max(k, 2), with_payload=True).points
    kept = [p for p in res if p.score >= floor]
    if len(kept) >= 2 and (kept[0].score - kept[1].score) < margin:
        return []                       # no discrimination -> say nothing
    return [Suggestion(str(p.id), float(p.score), dict(p.payload or {}))
            for p in kept[:k]]


def suggest_concepts(qc: QdrantClient, text: str, k: int = 5,
                     floor: float = 0.75) -> list[Suggestion]:
    """Authoring aid: which concepts does this problem statement exercise?"""
    return _search(qc, CONCEPTS, text, k, floor)


def suggest_misconception(qc: QdrantClient, delta_text: str, k: int = 3,
                          floor: float = 0.75) -> list[Suggestion]:
    """Fallback for a mutation delta with no exact `fault_signature` row.

    The result is a CANDIDATE for human confirmation. It must never be used to
    decay a concept: a wrong mapping corrupts a student's schedule invisibly and
    permanently, which is exactly the harm the exact-match table exists to avoid.
    """
    return _search(qc, MISCONCEPTIONS, delta_text, k, floor)


def near_duplicates(qc: QdrantClient, statement: str, k: int = 3,
                    floor: float = 0.80) -> list[Suggestion]:
    """Review-set diversity: is this problem too close to one already served?"""
    return _search(qc, PROBLEMS, statement, k, floor)


def stats(qc: QdrantClient) -> dict:
    out = {}
    for name in (CONCEPTS, PROBLEMS, MISCONCEPTIONS):
        out[name] = qc.count(name).count if qc.collection_exists(name) else 0
    return out
