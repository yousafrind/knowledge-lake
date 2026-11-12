import json
from pathlib import Path

import pytest
from lake_cli.main import main
from lake_core.db import make_engine, upgrade_to_head
from lake_core.objectstore import ObjectStore
from lake_ingest.explain import explain_path_json

TREE = Path(__file__).parent.parent / "evals" / "fixtures" / "disk_tree"
CONFIG = Path(__file__).parent.parent / "config"


@pytest.fixture
def lake(db_url: str, store: ObjectStore, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    upgrade_to_head(db_url)
    for k, v in {
        "DATABASE_URL": db_url,
        "S3_ENDPOINT": store.s3.meta.endpoint_url,
        "S3_KEY": "k",
        "S3_SECRET": "s",
        "S3_BUCKET": store.bucket,
        "CONFIG_DIR": str(CONFIG),
    }.items():
        monkeypatch.setenv(f"LAKE_{k}", v)
    main(["disk", str(TREE)])
    return make_engine(db_url)


def test_explain_indexed_and_ignored_paths(lake) -> None:  # type: ignore[no-untyped-def]
    rules = (CONFIG / "lakeignore.default").read_text()
    ok = json.loads(explain_path_json(lake, str(TREE / "docs/notes.md"), rules))
    assert (
        ok["indexed"] and ok["ignore"]["ignored"] is False and ok["content"]["type"] == "markdown"
    )
    venv = json.loads(explain_path_json(lake, str(TREE / "proj/.venv/lib/x.py"), rules))
    assert (
        not venv["indexed"] and venv["ignore"]["ignored"] and ".venv/" in venv["ignore"]["reason"]
    )
    git = json.loads(explain_path_json(lake, str(TREE / "proj/data/dump.csv"), rules))
    assert ".gitignore" in git["ignore"]["reason"]
    unknown = json.loads(explain_path_json(lake, "/nowhere/else.txt", rules))
    assert "never indexed" in unknown["note"]


def test_cli_explain_prints_json(lake, capsys) -> None:  # type: ignore[no-untyped-def]
    capsys.readouterr()
    main(["explain", str(TREE / "docs/private.md")])
    out = json.loads(capsys.readouterr().out)
    assert out["ignore"]["ignored"] and ".lakeignore" in out["ignore"]["reason"]
