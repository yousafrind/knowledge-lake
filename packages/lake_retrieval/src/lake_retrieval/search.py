"""Hybrid search: filter, dense + full-text in parallel queries, RRF fusion, citations."""

import re
from dataclasses import dataclass
from typing import Any

from lake_core.embedding import Embedder, to_pgvector
from sqlalchemy import Engine, text

RRF_K = 60
CANDIDATES = 50


@dataclass(frozen=True)
class Filters:
    source_types: list[str] | None = None
    tiers: list[str] | None = None  # "original" / "derived"


@dataclass(frozen=True)
class Passage:
    chunk_id: str
    text: str
    score: float
    citation: dict[str, Any]


def slug(section: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", section.lower()).strip("-")


def make_uri(sha: str, rev: int, section: str | None) -> str:
    return f"lake://{sha}#{rev}/{slug(section or '')}"


# Filters apply inside both queries, before ranking, so they shrink the candidate set.
_BASE = """
from chunk ch
join package p on p.id = ch.package_id and p.canonical
join content c on c.sha256 = p.content_sha256
where (cast(:types as text[]) is null or c.source_type = any(:types))
  and (cast(:tiers as text[]) is null or p.tier = any(:tiers))
"""
DENSE = text(
    "select ch.id " + _BASE + " and exists (select 1 from embedding e where e.chunk_id=ch.id "
    "and e.model=:model) order by (select e.vec from embedding e where e.chunk_id=ch.id "
    "and e.model=:model) <=> cast(:q as vector) limit :n"
)
SPARSE = text(
    "select ch.id " + _BASE + " and ch.tsv @@ websearch_to_tsquery('english', :qt) "
    "order by ts_rank_cd(ch.tsv, websearch_to_tsquery('english', :qt)) desc limit :n"
)
DETAIL = text(
    """
    select ch.id, ch.text, ch.section, p.content_sha256, p.rev, p.tier,
           p.manifest->>'title' as title,
           (select path from location l where l.content_sha256 = p.content_sha256
            order by l.seen_at limit 1) as location
    from chunk ch join package p on p.id = ch.package_id
    where ch.id = any(:ids)
    """
)


def rrf(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for pos, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + pos + 1)
    return scores


def search(
    engine: Engine,
    embedder: Embedder,
    query: str,
    *,
    limit: int = 10,
    filters: Filters | None = None,
    max_chars: int | None = None,
) -> list[Passage]:
    filters = filters or Filters()
    params: dict[str, Any] = {
        "types": filters.source_types,
        "tiers": filters.tiers,
        "n": CANDIDATES,
        "model": embedder.model,
        "q": to_pgvector(embedder.embed([query])[0]),
        "qt": query,
    }
    with engine.connect() as c:
        dense = [r[0] for r in c.execute(DENSE, params)]
        sparse = [r[0] for r in c.execute(SPARSE, params)]
        scores = rrf([dense, sparse])
        top = sorted(scores, key=lambda i: -scores[i])[:limit]
        if not top:
            return []
        rows = {r.id: r for r in c.execute(DETAIL, {"ids": top})}
    out: list[Passage] = []
    used = 0
    for cid in top:
        r = rows[cid]
        if max_chars is not None and out and used + len(r.text) > max_chars:
            break
        used += len(r.text)
        citation = {
            "uri": make_uri(r.content_sha256, r.rev, r.section),
            "title": r.title,
            "section": r.section,
            "location": r.location,
            "tier": r.tier,
        }
        out.append(Passage(cid, r.text, scores[cid], citation))
    return out
