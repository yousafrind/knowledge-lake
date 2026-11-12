from datetime import UTC, datetime

from lake_core.db import make_engine, upgrade_to_head
from lake_core.objectstore import ObjectStore, get_original, read_package
from lake_ingest.adapter import Item
from lake_ingest.registrar import Registrar
from sqlalchemy import text


def count(engine, table: str) -> int:  # type: ignore[no-untyped-def]
    with engine.connect() as c:
        return c.execute(text(f"select count(*) from {table}")).scalar_one()


def test_same_bytes_two_paths_and_same_path_twice(db_url: str, store: ObjectStore) -> None:
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    reg = Registrar(eng, store)
    a = reg.register(Item(b"hello", "/a.pdf", "upload"))
    b = reg.register(Item(b"hello", "/b.pdf", "upload"))
    c = reg.register(Item(b"hello", "/b.pdf", "upload"))
    assert (a.new_content, a.new_location) == (True, True)
    assert (b.new_content, b.new_location) == (False, True)
    assert (c.new_content, c.new_location) == (False, False)
    assert count(eng, "content") == 1 and count(eng, "location") == 2
    assert count(eng, "job") == 1
    assert get_original(store, a.content_sha256) == b"hello"
    with eng.connect() as conn:
        assert conn.execute(text("select processor from job")).scalar_one() == "parse"


def test_markdown_item_gets_package_and_chunk_job(db_url: str, store: ObjectStore) -> None:
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    r = Registrar(eng, store).register(
        Item(b"# T\nbody", "/n.md", "upload", datetime.now(UTC), markdown="# T\nbody")
    )
    manifest, files = read_package(store, r.content_sha256, 1)
    assert files["content.md"] == b"# T\nbody" and manifest["source_type"] == "markdown"
    assert count(eng, "package") == 1
    with eng.connect() as conn:
        assert conn.execute(text("select processor from job")).scalar_one() == "chunk"


def test_markdown_chunk_job_targets_the_package(db_url: str, store: ObjectStore) -> None:
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    r = Registrar(eng, store).register(Item(b"# T", "/n.md", "upload", markdown="# T"))
    with eng.connect() as c:
        assert c.execute(text("select target from job")).scalar_one() == f"{r.content_sha256}:1"
