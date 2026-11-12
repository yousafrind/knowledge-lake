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


def login(client: TestClient) -> None:
    assert client.post("/login", data={"password": "pw"}).status_code == 303


def doc_sha(client: TestClient) -> str:
    page = client.get("/", params={"path": "/notes"}).text
    return page.split("/doc/")[1].split('"')[0]


def test_edit_makes_new_derived_revision_and_old_one_stays(client: TestClient) -> None:
    login(client)
    sha = doc_sha(client)
    page = client.get(f"/doc/{sha}/edit").text
    assert "Replication" in page and 'id="pv"' in page
    assert "<h1" in client.post("/preview", data={"markdown": "# Hi"}).text
    r = client.post(f"/doc/{sha}/edit", data={"markdown": "# Databases\n\nEdited text."})
    assert r.status_code == 303
    doc = client.get(f"/doc/{sha}").text
    assert "Edited text." in doc and "rev 2 (current)" in doc and "rev 1" in doc
    assert "derived" in doc


def test_new_note_review_jobs_and_labels(client: TestClient) -> None:
    login(client)
    r = client.post("/new", data={"markdown": "# Fresh idea\n\nbody text"})
    assert r.status_code == 303
    page = client.get(r.headers["location"]).text
    assert "Fresh idea" in page and "body text" in page
    sha = r.headers["location"].rsplit("/", 1)[1]
    client.post(f"/doc/{sha}/label", data={"key": "topic", "value": "ideas"})
    assert "topic: ideas" in client.get(f"/doc/{sha}").text
    assert "No suggestions waiting" in client.get("/review").text
    jobs = client.get("/jobs").text
    assert "Sources" in jobs and "Nothing failing" in jobs


def test_group_decision_and_job_retry(client: TestClient, db_url: str) -> None:
    from sqlalchemy import text

    login(client)
    eng = make_engine(db_url)
    sha = doc_sha(client)
    with eng.begin() as c:
        gid = c.execute(
            text("insert into doc_group(kind,key) values ('version_family','k') returning id")
        ).scalar_one()
        c.execute(text("insert into doc_group_member values (:g,:s)"), {"g": gid, "s": sha})
        c.execute(
            text(
                "insert into job(id,processor,version,target,status,error) "
                "values ('j1','x','1','t','dead','boom')"
            )
        )
    assert "version family" in client.get("/review").text
    assert client.post(f"/review/group/{gid}/accept").status_code == 303
    assert "No suggestions waiting" in client.get("/review").text
    assert "boom" in client.get("/jobs").text
    client.post("/jobs/j1/retry")
    with eng.connect() as c:
        assert c.execute(text("select status from job where id='j1'")).scalar_one() == "pending"


def test_quarantine_shown_and_released_from_review(
    client: TestClient, db_url: str, store: ObjectStore
) -> None:
    login(client)
    eng = make_engine(db_url)
    body = "# Keys\n\nAKIAIOSFODNN7EXAMPLE"
    r = Registrar(eng, store).register(Item(body.encode(), "/k.md", "disk", markdown=body))
    assert r.quarantined
    page = client.get("/review").text
    assert "Held back" in page and "aws_access_key" in page and "/k.md" in page
    assert client.post(f"/quarantine/{r.content_sha256}/release").status_code == 303
    assert "Nothing held" in client.get("/review").text


def test_code_browser_and_chat_list(
    client: TestClient, db_url: str, store: ObjectStore, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    import subprocess

    from lake_cli.main import main as cli
    from lake_server.write_tools import save_conversation_json

    login(client)
    eng = make_engine(db_url)
    repo = tmp_path / "proj"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "a.py").write_text("def helper(x):\n    return x < 2\n")
    (repo / "pkg" / "b.py").write_text("from pkg.a import helper\n\nhelper(1)\n")
    for args in (
        ["init", "-q"],
        ["add", "."],
        ["-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "i"],
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    import os

    for k, v in {
        "DATABASE_URL": db_url,
        "S3_ENDPOINT": store.s3.meta.endpoint_url,
        "S3_KEY": "k",
        "S3_SECRET": "s",
        "S3_BUCKET": store.bucket,
        "EMBEDDER": "hash",
    }.items():
        os.environ[f"LAKE_{k}"] = v
    try:
        cli(["code", str(repo)])
        cli(["work"])
    finally:
        for k in ["DATABASE_URL", "S3_ENDPOINT", "S3_KEY", "S3_SECRET", "S3_BUCKET", "EMBEDDER"]:
            os.environ.pop(f"LAKE_{k}", None)
    assert "proj" in client.get("/code").text
    assert "pkg" in client.get("/code/proj").text
    assert "a.py" in client.get("/code/proj", params={"path": "pkg"}).text
    page = client.get("/code/proj/file", params={"path": "pkg/a.py", "symbol": "helper"}).text
    assert 'id="L1"' in page and "x &lt; 2" in page  # source is HTML-escaped
    assert "pkg/b.py:3" in page and "used where?" in page
    assert client.get("/code/proj/file", params={"path": "nope.py"}).status_code == 404
    save_conversation_json(
        eng,
        Registrar(eng, store),
        "Design chat",
        [{"role": "user", "content": "hi"}],
        tags=["lake"],
    )
    chats = client.get("/chats").text
    assert "Design chat" in chats and "#lake" in chats and "mcp" in chats
    assert "Design chat" in client.get("/chats", params={"tag": "lake"}).text
    assert "Design chat" not in client.get("/chats", params={"origin": "claude"}).text
