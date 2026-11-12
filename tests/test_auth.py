import asyncio
import json

import pytest
from lake_core.db import make_engine, upgrade_to_head
from lake_core.embedding import HashEmbedder
from lake_core.tokens import new_token
from lake_server.auth import FileTokenVerifier, load_auth
from lake_server.mcp_tools import create_server
from lake_server.ratelimit import RateLimit
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

TOML = """
public_url = "https://lake.example"
[limits]
per_minute = 2

[tokens.reader]
sha256 = "{reader}"
scopes = ["read"]

[tokens.boss]
sha256 = "{boss}"
scopes = ["read", "code:read", "write", "admin"]
"""


@pytest.fixture
def tokens(tmp_path):  # type: ignore[no-untyped-def]
    t_read, h_read = new_token()
    t_boss, h_boss = new_token()
    f = tmp_path / "tokens.toml"
    f.write_text(TOML.format(reader=h_read, boss=h_boss))
    return f, t_read, t_boss


def test_verifier_knows_tokens_and_their_scopes(tokens) -> None:  # type: ignore[no-untyped-def]
    f, t_read, _ = tokens
    v = FileTokenVerifier(f)
    got = asyncio.run(v.verify_token(t_read))
    assert got is not None and got.scopes == ["read"] and got.client_id == "reader"
    assert asyncio.run(v.verify_token("nope")) is None


def _call(server, tool: str, args: dict, scopes: list[str] | None):  # type: ignore[no-untyped-def]
    async def go():  # type: ignore[no-untyped-def]
        if scopes is not None:
            tok = AccessToken(token="t", client_id="c", scopes=scopes)
            auth_context_var.set(AuthenticatedUser(tok))
        return await server.call_tool(tool, args)

    return asyncio.run(go())


def _denied(server, tool: str, args: dict, scopes: list[str] | None) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(Exception) as e:
        _call(server, tool, args, scopes)
    assert isinstance(e.value.__cause__, PermissionError), repr(e.value)


def test_each_tool_needs_its_scope(db_url: str) -> None:
    upgrade_to_head(db_url)
    server = create_server(make_engine(db_url), HashEmbedder(), enforce_scopes=True)
    assert _call(server, "search", {"query": "x"}, ["read"]) is not None
    _denied(server, "code_search", {"query": "x"}, ["read"])
    _denied(server, "explain_path", {"path": "/x"}, ["read", "write"])
    _denied(server, "search", {"query": "x"}, None)  # no token at all


def test_without_enforcement_everything_is_open(db_url: str) -> None:
    upgrade_to_head(db_url)
    server = create_server(make_engine(db_url), HashEmbedder())
    assert json.loads(_call(server, "search", {"query": "x"}, None).content[0].text)  # type: ignore[union-attr]


def test_http_needs_a_valid_bearer_token(db_url: str, tokens) -> None:  # type: ignore[no-untyped-def]
    f, t_read, _ = tokens
    upgrade_to_head(db_url)
    server = create_server(make_engine(db_url), HashEmbedder(), enforce_scopes=True, **load_auth(f))
    app = server.streamable_http_app()
    with TestClient(app) as c:
        body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        hdr = {"Accept": "application/json, text/event-stream"}
        assert c.post("/mcp", json=body, headers=hdr).status_code == 401
        bad = {**hdr, "Authorization": "Bearer wrong"}
        assert c.post("/mcp", json=body, headers=bad).status_code == 401
        ok = {**hdr, "Authorization": f"Bearer {t_read}"}
        assert c.post("/mcp", json=body, headers=ok).status_code != 401


def test_rate_limit_counts_per_token() -> None:
    app = Starlette(
        routes=[Route("/", lambda r: PlainTextResponse("hi"))],
        middleware=[Middleware(RateLimit, per_minute=2)],
    )
    with TestClient(app) as c:
        a = {"Authorization": "Bearer a"}
        b = {"Authorization": "Bearer b"}
        assert [c.get("/", headers=a).status_code for _ in range(3)] == [200, 200, 429]
        assert c.get("/", headers=b).status_code == 200


def test_app_turns_auth_on_when_tokens_file_exists(  # type: ignore[no-untyped-def]
    db_url: str, tokens, tmp_path, monkeypatch
) -> None:
    from lake_server.app import build_app

    f, _, _ = tokens
    upgrade_to_head(db_url)
    for k, v in {
        "DATABASE_URL": db_url,
        "S3_ENDPOINT": "http://localhost:1",
        "S3_KEY": "k",
        "S3_SECRET": "s",
        "EMBEDDER": "hash",
        "CONFIG_DIR": str(f.parent),
    }.items():
        monkeypatch.setenv(f"LAKE_{k}", v)
    (f.parent / "tokens.toml").exists()
    with TestClient(build_app()) as c:
        hdr = {"Accept": "application/json, text/event-stream"}
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers=hdr)
        assert r.status_code == 401
