from lake_core.db import make_engine, upgrade_to_head
from lake_core.embedding import HashEmbedder
from lake_core.objectstore import ObjectStore
from lake_ingest.adapter import Item
from lake_ingest.registrar import Registrar
from lake_processors.chunk import ChunkProcessor
from lake_processors.contract import Context, Registry
from lake_processors.embed import EmbedProcessor
from lake_processors.loop import run_until_idle
from lake_retrieval.search import Filters, rrf, search

A = "# Databases\n\n## Replication\n\nPostgres replication copies data between servers."
B = "# Kitchen\n\n## Bread\n\nBake the bread in a hot oven."


def build(db_url: str, store: ObjectStore):  # type: ignore[no-untyped-def]
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    reg = Registrar(eng, store)
    reg.register(Item(A.encode(), "/db.md", "upload", markdown=A))
    reg.register(Item(B.encode(), "/kitchen.txt", "upload", source_type="text", markdown=B))
    r = Registry()
    r.add(ChunkProcessor())
    emb = HashEmbedder()
    r.add(EmbedProcessor(emb))
    run_until_idle(Context(eng, store), r)
    return eng, emb


def test_rrf_rewards_agreement() -> None:
    s = rrf([["a", "b"], ["b", "c"]])
    assert s["b"] > s["a"] > s["c"]


def test_hybrid_search_returns_cited_passages(db_url: str, store: ObjectStore) -> None:
    eng, emb = build(db_url, store)
    hits = search(eng, emb, "how does replication work")
    top = hits[0]
    assert "replication" in top.text.lower()
    assert top.citation["uri"].startswith("lake://") and top.citation["uri"].endswith(
        "#1/databases-replication"
    )
    assert top.citation["section"] == "Databases > Replication"
    assert top.citation["location"] == "/db.md" and top.citation["tier"] == "original"


def test_filters_cut_candidates_before_search(db_url: str, store: ObjectStore) -> None:
    eng, emb = build(db_url, store)
    hits = search(eng, emb, "bread oven replication", filters=Filters(source_types=["markdown"]))
    assert hits and all(h.citation["location"] == "/db.md" for h in hits)
    assert search(eng, emb, "bread", filters=Filters(tiers=["derived"])) == []


def test_token_budget_trims(db_url: str, store: ObjectStore) -> None:
    eng, emb = build(db_url, store)
    assert len(search(eng, emb, "bread replication servers", max_chars=10)) == 1
