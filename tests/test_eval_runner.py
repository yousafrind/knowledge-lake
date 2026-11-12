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


def test_gate_requires_a_real_improvement() -> None:
    from gate import verdict

    base = {"recall_at_k": 0.70, "mrr": 0.50}
    assert verdict(base, {"recall_at_k": 0.80, "mrr": 0.50})["adopt"]
    assert verdict(base, {"recall_at_k": 0.70, "mrr": 0.58})["adopt"]
    assert not verdict(base, {"recall_at_k": 0.72, "mrr": 0.51})["adopt"]  # inside the margin
    assert not verdict(base, {"recall_at_k": 0.90, "mrr": 0.40})[
        "adopt"
    ]  # better one, much worse other


def test_link_expansion_adds_linked_document(db_url: str, store: ObjectStore) -> None:
    from lake_cli.main import build_registry
    from lake_core.db import make_engine
    from lake_core.embedding import HashEmbedder
    from lake_ingest.adapter import Item
    from lake_ingest.registrar import Registrar
    from lake_processors.contract import Context
    from lake_processors.loop import run_until_idle
    from lake_retrieval.graph import search_with_links
    from lake_retrieval.search import search

    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    reg = Registrar(eng, store)
    a = "# Overview\n\nThe zebrafish pipeline is described in [the details](details.md)."
    b = "# Details\n\nSteps: incubate, image, quantify fluorescence."
    reg.register(Item(a.encode(), "/d/overview.md", "disk", markdown=a))
    reg.register(Item(b.encode(), "/d/details.md", "disk", markdown=b))
    for i in range(3):  # filler that mentions the query words, so Details ranks below them
        f = f"# Filler {i}\n\nA pipeline note number {i} about zebrafish tanks and cleaning."
        reg.register(Item(f.encode(), f"/f/{i}.md", "disk", markdown=f))
    run_until_idle(Context(eng, store), build_registry("hash"))
    emb = HashEmbedder()
    plain = {p.citation["title"] for p in search(eng, emb, "zebrafish pipeline", limit=3)}
    out = search_with_links(eng, emb, "zebrafish pipeline", limit=3)
    assert "Details" not in plain
    assert [p.citation["title"] for p in out if p.citation.get("via") == "link"] == ["Details"]
    assert len(out) == 3
