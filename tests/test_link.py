from pathlib import Path

import pytest
from lake_cli.main import add, build_registry
from lake_core.db import make_engine, upgrade_to_head
from lake_core.objectstore import ObjectStore
from lake_processors.contract import Context
from lake_processors.link import resolve_ref
from lake_processors.loop import run_until_idle
from sqlalchemy import text


def test_resolve_ref() -> None:
    assert resolve_ref("/a/b/x.md", "../c/y.md#top") == "/a/c/y.md"
    assert resolve_ref("/a/x.md", "https://e.com/p") == "https://e.com/p"
    assert resolve_ref("https://e.com/docs/x.html", "y.html") == "https://e.com/docs/y.html"
    assert resolve_ref("/a/x.md", "mailto:me@e.com") is None
    assert resolve_ref("/a/x.md", "#only-fragment") is None


def test_links_resolve_even_when_target_arrives_later(
    db_url: str, store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upgrade_to_head(db_url)
    for k, v in {
        "DATABASE_URL": db_url,
        "S3_ENDPOINT": store.s3.meta.endpoint_url,
        "S3_KEY": "k",
        "S3_SECRET": "s",
        "S3_BUCKET": store.bucket,
    }.items():
        monkeypatch.setenv(f"LAKE_{k}", v)
    (tmp_path / "a.md").write_text("# A\n\nSee [the b note](sub/b.md) and [web](https://x.org).")
    add(str(tmp_path))
    eng = make_engine(db_url)
    ctx = Context(eng, store)
    run_until_idle(ctx, build_registry("hash"))
    with eng.connect() as c:
        rows = c.execute(text("select dst_ref, dst_sha from edge order by dst_ref")).all()
    assert len(rows) == 2 and all(r.dst_sha is None for r in rows)  # b.md not added yet
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text("# B\n\nbody")
    add(str(tmp_path))
    run_until_idle(ctx, build_registry("hash"))
    with eng.connect() as c:
        resolved = c.execute(text("select dst_ref from edge where dst_sha is not null")).all()
    assert [r[0] for r in resolved] == [str(tmp_path / "sub" / "b.md")]
