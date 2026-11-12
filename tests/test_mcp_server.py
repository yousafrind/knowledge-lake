import asyncio
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
from lake_server.mcp_tools import create_server, fetch_json, search_json
from sqlalchemy import text

A = "# Databases\n\n## Replication\n\nPostgres replication copies data.\n\nMore on replication."


@pytest.fixture
def lake(db_url: str, store: ObjectStore):  # type: ignore[no-untyped-def]
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    Registrar(eng, store).register(Item(A.encode(), "/db.md", "upload", markdown=A))
    r = Registry()
    r.add(ChunkProcessor())
    r.add(EmbedProcessor(HashEmbedder()))
    run_until_idle(Context(eng, store), r)
    return eng


def test_search_then_fetch_round_trip(lake) -> None:  # type: ignore[no-untyped-def]
    res = json.loads(search_json(lake, HashEmbedder(), "replication"))["results"]
    assert res and res[0]["id"].startswith("lake://")
    doc = json.loads(fetch_json(lake, res[0]["id"]))
    assert "More on replication" in doc["text"] and doc["id"] == res[0]["id"]


def test_fetch_rejects_bad_ids(lake) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        fetch_json(lake, "not-a-uri")


def test_server_exposes_the_read_tools_over_mcp(lake) -> None:  # type: ignore[no-untyped-def]
    server = create_server(lake, HashEmbedder())

    async def go() -> tuple[list[str], str]:
        tools = [t.name for t in await server.list_tools()]
        out = await server.call_tool("search", {"query": "replication"})
        return tools, out.content[0].text  # type: ignore[union-attr]

    tools, body = asyncio.run(go())
    assert (
        sorted(tools)
        == [
            "code_dependency_docs",
            "code_file_outline",
            "code_find_references",
            "code_find_symbol",
            "code_get_file",
            "code_repo_map",
            "code_search",
            "explain_path",
            "fetch",
            "get_document",
            "neighbors",
            "query",
            "resolve_source",
            "search",
        ]
        and "results" in body
    )


def test_read_tools(lake) -> None:  # type: ignore[no-untyped-def]
    from lake_server.mcp_tools import (
        get_document_json,
        neighbors_json,
        query_json,
        resolve_source_json,
    )

    hit = json.loads(search_json(lake, HashEmbedder(), "replication"))["results"][0]
    doc = json.loads(get_document_json(lake, hit["id"]))
    assert doc["outline"] == ["Databases > Replication"] and doc["revisions"][0]["canonical"]
    assert json.loads(resolve_source_json(lake, hit["id"]))["locations"][0]["path"] == "/db.md"
    none = json.loads(query_json(lake, HashEmbedder(), "replication", source_type="pdf"))
    assert none["results"] == []
    some = json.loads(query_json(lake, HashEmbedder(), "replication", source_type="markdown"))
    assert some["results"]
    n = json.loads(neighbors_json(lake, HashEmbedder(), hit["id"]))
    assert n["links_out"] == [] and n["similar"] == []  # only one document in this lake
    with pytest.raises(ValueError):
        get_document_json(lake, "zz")


def test_neighbors_finds_similar_document(db_url: str, store: ObjectStore) -> None:
    from lake_server.mcp_tools import neighbors_json

    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    reg = Registrar(eng, store)
    docs = {
        "/a.md": "# A\n\nraft leader election votes majority",
        "/b.md": "# B\n\nleader election needs a majority of votes in raft",
        "/c.md": "# C\n\nsourdough starter flour water",
    }
    for path, md in docs.items():
        reg.register(Item(md.encode(), path, "upload", markdown=md))
    r = Registry()
    r.add(ChunkProcessor())
    r.add(EmbedProcessor(HashEmbedder()))
    run_until_idle(Context(eng, store), r)
    with eng.connect() as c:
        a = c.execute(
            text("select content_sha256 from package where manifest->>'title'='A'")
        ).scalar_one()
    sim = json.loads(neighbors_json(eng, HashEmbedder(), a))["similar"]
    assert [s["title"] for s in sim][0] == "B"
