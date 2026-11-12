# ADR 0002: LightRAG pilot deferred; the eval gate and a cheap graph option are built

**Status:** accepted (W-029)

**Was:** W-029 = run a LightRAG pilot and adopt it only if it beats plain hybrid search on the golden set.

**Now:** the gate (`evals/gate.py`) and a comparison path (`evals/run_eval.py --retriever links`) are built and tested. LightRAG itself was **not run**: it needs an LLM for entity and relation extraction, and this build environment has no LLM access and no outbound network. A cheaper graph option that needs no LLM was built instead: `lake_retrieval.graph.search_with_links`, which adds the best passage of documents linked to the top hits using the explicit link table.

**Why:** the architecture said graph work proceeds only if it wins on the evals. Running the gate needs a real embedder and real documents, which exist only on the owner's machine.

**To finish the pilot:** wrap LightRAG behind the same `retriever(engine, embedder, query, limit=k) -> list[Passage]` signature, run `evaluate()` for both, and call `gate.verdict(baseline, candidate)`. Adopt only if `adopt` is true on a golden set built from real documents (the fixture set in the repo is too small to decide).
