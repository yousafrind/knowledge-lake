import json

import pytest
from lake_core.db import make_engine, upgrade_to_head
from lake_core.embedding import HashEmbedder
from lake_core.objectstore import ObjectStore
from lake_ingest.adapter import Item
from lake_ingest.registrar import Registrar
from lake_processors.chunk import ChunkProcessor
from lake_processors.contract import Context, Registry
from lake_processors.embed import EmbedProcessor
from lake_processors.loop import run_until_idle
from lake_retrieval.research import research_json
from sqlalchemy import text

DOCS = {
    "/a.md": "# Replication\n\nPostgres replication streams the write ahead log.",
    "/b.md": "# Failover\n\nPromote a standby when the primary dies.",
    "/c.md": "# Gardening\n\nTomatoes need sun.",
}


@pytest.fixture
def lake(db_url: str, store: ObjectStore):  # type: ignore[no-untyped-def]
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    reg = Registrar(eng, store)
    for path, md in DOCS.items():
        reg.register(Item(md.encode(), path, "upload", markdown=md))
    reg.register(
        Item(
            b"x",
            "/d.md",
            "upload",
            markdown="# Replication notes\n\nreplication summary by a model",
            tier="derived",
        )
    )
    r = Registry()
    r.add(ChunkProcessor())
    r.add(EmbedProcessor(HashEmbedder()))
    run_until_idle(Context(eng, store), r)
    with eng.begin() as c:
        sha = {
            p: c.execute(
                text("select content_sha256 from location where path=:p"), {"p": p}
            ).scalar()
            for p in [*DOCS, "/d.md"]
        }
        c.execute(
            text("insert into edge (src_sha, dst_ref, dst_sha) values (:s, '/b.md', :d)"),
            {"s": sha["/a.md"], "d": sha["/b.md"]},
        )
    return eng, sha


def test_research_returns_evidence_and_link_graph(lake) -> None:  # type: ignore[no-untyped-def]
    eng, sha = lake
    out = json.loads(research_json(eng, HashEmbedder(), "postgres replication"))
    docs = {n["sha"] for n in out["documents"]}
    assert sha["/a.md"] in docs and sha["/b.md"] in docs  # b arrives through the link
    assert {"src": sha["/a.md"], "dst": sha["/b.md"]} in out["links"]
    assert all(e["tier"] == "original" for e in out["evidence"])  # no self-citing
    assert sha["/d.md"] not in docs


def test_research_can_include_derived_when_asked(lake) -> None:  # type: ignore[no-untyped-def]
    eng, sha = lake
    out = json.loads(research_json(eng, HashEmbedder(), "replication", include_derived=True))
    assert sha["/d.md"] in {n["sha"] for n in out["documents"]}
