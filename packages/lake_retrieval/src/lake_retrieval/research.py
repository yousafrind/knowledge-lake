"""Research: a topic in, an evidence set plus the links between the documents it touches.

Search with link expansion, original documents only (derived ones are model output and would
make the lake cite itself). Deterministic: no LLM.
"""

import json

from lake_core.embedding import Embedder
from sqlalchemy import Engine, text

from lake_retrieval.graph import search_with_links
from lake_retrieval.search import Filters

LINKS = text(
    "select src_sha, dst_sha from edge "
    "where src_sha = any(:s) and dst_sha = any(:s) and src_sha <> dst_sha"
)


def research_json(
    engine: Engine,
    embedder: Embedder,
    topic: str,
    limit: int = 10,
    include_derived: bool = False,
) -> str:
    filters = None if include_derived else Filters(tiers=["original"])
    hits = search_with_links(engine, embedder, topic, limit=limit, filters=filters)
    docs: dict[str, str | None] = {}
    evidence = []
    for h in hits:
        c = h.citation
        sha = c["uri"][len("lake://") : len("lake://") + 64]
        docs.setdefault(sha, c["title"])
        evidence.append(
            {
                "id": c["uri"],
                "document": sha,
                "section": c["section"],
                "text": h.text,
                "tier": c["tier"],
                "via": c.get("via", "search"),
                "score": round(h.score, 5),
            }
        )
    with engine.connect() as conn:
        links = [
            {"src": r.src_sha, "dst": r.dst_sha}
            for r in conn.execute(LINKS, {"s": list(docs)}).all()
        ]
    return json.dumps(
        {
            "topic": topic,
            "documents": [{"sha": s, "title": t} for s, t in docs.items()],
            "evidence": evidence,
            "links": links,
        }
    )
