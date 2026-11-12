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


def test_server_exposes_exactly_search_and_fetch_over_mcp(lake) -> None:  # type: ignore[no-untyped-def]
    server = create_server(lake, HashEmbedder())

    async def go() -> tuple[list[str], str]:
        tools = [t.name for t in await server.list_tools()]
        out = await server.call_tool("search", {"query": "replication"})
        return tools, out.content[0].text  # type: ignore[union-attr]

    tools, body = asyncio.run(go())
    assert sorted(tools) == ["fetch", "search"] and "results" in body
