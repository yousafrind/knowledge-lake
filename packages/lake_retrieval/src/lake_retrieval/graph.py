"""Optional graph expansion: pull in the best passage from documents linked to the top hits.

Up to RESERVE of the `limit` slots go to linked passages (displacing the weakest plain hits).

Uses only explicit links (the `edge` table), no LLM. Off by default; callers ask for it.
"""

from lake_core.embedding import Embedder, to_pgvector
from sqlalchemy import Engine, text

from lake_retrieval.search import Filters, Passage, make_uri, search

NEIGHBOUR_WEIGHT = 0.5  # a linked passage scores half of the hit that led to it
SEEDS = 3
RESERVE = 2  # slots held back for linked passages, so expansion can actually add evidence

NEIGHBOUR_BEST = text(
    """
    select ch.id, ch.text, ch.section, p.content_sha256, p.rev, p.tier,
           p.manifest->>'title' as title,
           (select path from location l where l.content_sha256 = p.content_sha256
            order by l.seen_at limit 1) as location
    from chunk ch
    join package p on p.id = ch.package_id and p.canonical
    join embedding e on e.chunk_id = ch.id and e.model = :model
    where p.content_sha256 = :sha
    order by e.vec <=> cast(:q as vector) limit 1
    """
)
LINKED = text(
    """
    select dst_sha as sha from edge where src_sha = :s and dst_sha is not null
    union
    select src_sha from edge where dst_sha = :s
    """
)


def search_with_links(
    engine: Engine,
    embedder: Embedder,
    query: str,
    *,
    limit: int = 10,
    filters: Filters | None = None,
) -> list[Passage]:
    base = search(engine, embedder, query, limit=limit, filters=filters)
    seen = {p.chunk_id for p in base}
    q = to_pgvector(embedder.embed([query])[0])
    extra: list[Passage] = []
    with engine.connect() as c:
        for p in base[:SEEDS]:
            sha = p.citation["uri"][len("lake://") : len("lake://") + 64]
            for (nsha,) in c.execute(LINKED, {"s": sha}).all():
                r = c.execute(
                    NEIGHBOUR_BEST, {"sha": nsha, "model": embedder.model, "q": q}
                ).first()
                if r is None or r.id in seen:
                    continue
                seen.add(r.id)
                citation = {
                    "uri": make_uri(r.content_sha256, r.rev, r.section),
                    "title": r.title,
                    "section": r.section,
                    "location": r.location,
                    "tier": r.tier,
                    "via": "link",
                }
                extra.append(Passage(r.id, r.text, p.score * NEIGHBOUR_WEIGHT, citation))
    extra = sorted(extra, key=lambda x: -x.score)[: min(RESERVE, limit)]
    kept = base[: limit - len(extra)]
    return sorted([*kept, *extra], key=lambda x: -x.score)
