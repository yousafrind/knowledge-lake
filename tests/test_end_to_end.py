"""The walking skeleton: add -> work -> search/fetch over MCP."""

import json
from pathlib import Path

import pytest
from lake_cli.main import main
from lake_core.db import make_engine, upgrade_to_head
from lake_core.embedding import make_embedder
from lake_core.objectstore import ObjectStore
from lake_server.mcp_tools import fetch_json, search_json


def test_add_work_search_fetch(
    db_url: str, store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upgrade_to_head(db_url)
    for k, v in {
        "DATABASE_URL": db_url,
        "S3_ENDPOINT": store.s3.meta.endpoint_url,
        "S3_KEY": "k",
        "S3_SECRET": "s",
        "S3_BUCKET": store.bucket,
        "EMBEDDER": "hash",
    }.items():
        monkeypatch.setenv(f"LAKE_{k}", v)
    (tmp_path / "book.pdf").write_bytes(b"# Raft\n\nRaft elects a leader by majority vote.")
    (tmp_path / "note.md").write_text("# Notes\n\nSourdough needs a long rise.")
    main(["add", str(tmp_path)])
    main(["work"])
    eng = make_engine(db_url)
    hits = json.loads(search_json(eng, make_embedder("hash"), "who elects the leader"))["results"]
    assert "leader" in hits[0]["text"]
    assert "majority vote" in json.loads(fetch_json(eng, hits[0]["id"]))["text"]
