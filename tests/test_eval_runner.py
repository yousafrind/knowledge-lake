import sys
from pathlib import Path

import pytest
from lake_core.db import upgrade_to_head
from lake_core.objectstore import ObjectStore

sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))


def test_eval_runner_scores_golden_set(
    db_url: str, store: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from run_eval import evaluate

    upgrade_to_head(db_url)
    for k, v in {
        "DATABASE_URL": db_url,
        "S3_ENDPOINT": store.s3.meta.endpoint_url,
        "S3_KEY": "k",
        "S3_SECRET": "s",
        "S3_BUCKET": store.bucket,
    }.items():
        monkeypatch.setenv(f"LAKE_{k}", v)
    r = evaluate("hash")
    assert r["questions"] == 8
    assert r["recall_at_k"] >= 0.75  # floor for the offline hash embedder; raise with real models
