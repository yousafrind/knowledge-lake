"""What each kind of client relies on, checked over real HTTP with the MCP client.

ChatGPT's connector: tools `search` and `fetch`, one string argument each, fixed result shapes.
Claude / Codex: bearer token, scopes, tools listed by name. All: results are evidence with
citations, never a generated answer.
"""

import asyncio
import json
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
from lake_core.db import make_engine, upgrade_to_head
from lake_core.embedding import HashEmbedder
from lake_core.objectstore import ObjectStore
from lake_core.tokens import new_token
from lake_ingest.adapter import Item
from lake_ingest.registrar import Registrar
from lake_processors.chunk import ChunkProcessor
from lake_processors.contract import Context, Registry
from lake_processors.embed import EmbedProcessor
from lake_processors.loop import run_until_idle
from lake_server.auth import load_auth
from lake_server.mcp_tools import create_server
from mcp.client.session import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

DOC = "# Databases\n\n## Replication\n\nPostgres replication copies data to a standby."


@pytest.fixture
def server(db_url: str, store: ObjectStore, tmp_path) -> Iterator[tuple[str, str, str]]:  # type: ignore[no-untyped-def]
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    Registrar(eng, store).register(Item(DOC.encode(), "/db.md", "upload", markdown=DOC))
    reg = Registry()
    reg.add(ChunkProcessor())
    reg.add(EmbedProcessor(HashEmbedder()))
    run_until_idle(Context(eng, store), reg)

    t_read, h_read = new_token()
    t_all, h_all = new_token()
    f = tmp_path / "tokens.toml"
    f.write_text(
        'public_url = "http://127.0.0.1"\n'
        f'[tokens.reader]\nsha256 = "{h_read}"\nscopes = ["read"]\n'
        f'[tokens.all]\nsha256 = "{h_all}"\nscopes = ["read", "code:read", "write", "admin"]\n'
    )
    app = create_server(
        eng, HashEmbedder(), enforce_scopes=True, **load_auth(f)
    ).streamable_http_app()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp", t_read, t_all
    srv.should_exit = True
    th.join(5)


def _run(url: str, token: str, fn: Any) -> Any:
    async def go() -> Any:
        client = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
        async with client, streamable_http_client(url, http_client=client) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                return await fn(session)

    return asyncio.run(go())


def test_chatgpt_shape_search_then_fetch(server) -> None:  # type: ignore[no-untyped-def]
    url, t_read, _ = server

    async def go(s: ClientSession) -> tuple[Any, Any, Any]:
        tools = {t.name: t for t in (await s.list_tools()).tools}
        found = json.loads((await s.call_tool("search", {"query": "replication"})).content[0].text)  # type: ignore[union-attr]
        doc = json.loads(
            (await s.call_tool("fetch", {"id": found["results"][0]["id"]})).content[0].text  # type: ignore[union-attr]
        )
        return tools, found, doc

    tools, found, doc = _run(url, t_read, go)
    for name, arg in (("search", "query"), ("fetch", "id")):
        schema = tools[name].input_schema
        assert list(schema["properties"]) == [arg] and schema["required"] == [arg]
        assert schema["properties"][arg]["type"] == "string"
    first = found["results"][0]
    assert {"id", "title", "url", "text"} <= set(first) and first["id"].startswith("lake://")
    assert {"id", "title", "text", "url", "metadata"} <= set(doc) and "standby" in doc["text"]
    assert "answer" not in found and "answer" not in doc  # evidence, never a generated answer


def test_tools_listed_by_name(server) -> None:  # type: ignore[no-untyped-def]
    url, t_read, _ = server

    async def go(s: ClientSession) -> list[str]:
        return sorted(t.name for t in (await s.list_tools()).tools)

    names = _run(url, t_read, go)
    assert {"search", "fetch", "query", "research", "get_document", "neighbors"} <= set(names)
    assert {"code_search", "save_document", "explain_path"} <= set(names)


def test_scopes_hold_over_http(server) -> None:  # type: ignore[no-untyped-def]
    url, t_read, t_all = server

    async def code(s: ClientSession) -> Any:
        return await s.call_tool("code_search", {"query": "x"})

    denied = _run(url, t_read, code)
    assert denied.is_error  # the SDK hides the reason behind a generic tool error
    allowed = _run(url, t_all, code)
    assert not allowed.is_error


def test_wrong_token_cannot_connect(server) -> None:  # type: ignore[no-untyped-def]
    url, _, _ = server
    with pytest.raises(BaseException):  # noqa: B017, PT011  the transport raises on 401
        _run(url, "wrong", lambda s: asyncio.sleep(0))
