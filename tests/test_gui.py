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
from lake_server.gui import build_gui_routes, render_markdown
from starlette.applications import Starlette
from starlette.testclient import TestClient

A = "# Databases\n\n## Replication\n\nPostgres replication <script>alert(1)</script> copies data."


@pytest.fixture
def client(db_url: str, store: ObjectStore) -> TestClient:
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    Registrar(eng, store).register(Item(A.encode(), "/notes/db.md", "upload", markdown=A))
    r = Registry()
    r.add(ChunkProcessor())
    emb = HashEmbedder()
    r.add(EmbedProcessor(emb))
    run_until_idle(Context(eng, store), r)
    routes, mw = build_gui_routes(eng, emb, store, "pw")
    return TestClient(Starlette(routes=routes, middleware=mw), follow_redirects=False)


def test_requires_login(client: TestClient) -> None:
    assert client.get("/").status_code == 303
    assert client.post("/login", data={"password": "bad"}).status_code == 401


def test_browse_search_read(client: TestClient) -> None:
    assert client.post("/login", data={"password": "pw"}).status_code == 303
    assert "notes" in client.get("/").text
    page = client.get("/", params={"path": "/notes"}).text
    assert "Databases" in page and "/doc/" in page
    sha = page.split("/doc/")[1].split('"')[0]
    hits = client.get("/search", params={"q": "replication"}).text
    assert "Databases" in hits and "#databases-replication" in hits
    doc = client.get(f"/doc/{sha}").text
    assert 'id="databases-replication"' in doc and "rev 1 (current)" in doc
    assert "Links out" in doc and "Linked from" in doc
    assert "<script>alert" not in doc  # raw HTML in documents is escaped


def test_render_markdown_ids_match_citation_slugs() -> None:
    html, outline = render_markdown("# A\n\n## B c\n")
    assert [o["anchor"] for o in outline] == ["a", "a-b-c"] and 'id="a-b-c"' in html
