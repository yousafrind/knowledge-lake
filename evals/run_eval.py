"""Score retrieval on the golden set. Usage: python evals/run_eval.py [--embedder hash|bge-small]

Needs LAKE_* settings (a scratch database is recommended). Ingests evals/fixtures/docs, runs
the jobs, asks every golden question, reports recall@k and MRR, and writes evals/runs/<time>.json.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from lake_cli.main import add, build_registry
from lake_core.db import make_engine
from lake_core.embedding import make_embedder
from lake_core.objectstore import ObjectStore
from lake_core.settings import load_settings
from lake_processors.contract import Context
from lake_processors.loop import run_until_idle
from lake_retrieval.search import search

HERE = Path(__file__).parent


def evaluate(embedder_name: str, k: int = 5) -> dict:  # type: ignore[type-arg]
    s = load_settings()
    add(str(HERE / "fixtures" / "docs"))
    store = ObjectStore(s.s3_endpoint, s.s3_key, s.s3_secret, s.s3_bucket)
    engine = make_engine(s.database_url)
    run_until_idle(Context(engine, store), build_registry(embedder_name))
    emb = make_embedder(embedder_name)
    rows, hits, rr = [], 0, 0.0
    questions = [json.loads(line) for line in (HERE / "golden" / "questions.jsonl").open()]
    for q in questions:
        results = search(engine, emb, q["q"], limit=k)
        rank = next(
            (
                i + 1
                for i, p in enumerate(results)
                if p.citation["location"].endswith(q["doc"]) and q["contains"] in p.text
            ),
            None,
        )
        hits += rank is not None
        rr += 1 / rank if rank else 0
        rows.append({"q": q["q"], "rank": rank})
    n = len(questions)
    return {
        "embedder": embedder_name,
        "k": k,
        "questions": n,
        "recall_at_k": hits / n,
        "mrr": rr / n,
        "rows": rows,
        "at": datetime.now(UTC).isoformat(),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--embedder", default="hash")
    result = evaluate(ap.parse_args().embedder)
    out = HERE / "runs" / f"{result['at'][:19].replace(':', '-')}-{result['embedder']}.json"
    out.write_text(json.dumps(result, indent=2))
    print(f"recall@{result['k']}={result['recall_at_k']:.2f} mrr={result['mrr']:.2f} -> {out.name}")
