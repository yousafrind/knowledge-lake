# Build Register

What has actually been built, where it lives, and why it is shaped that way.
Newest item last. Add an entry in the same commit that finishes a work item.

Entry format: **what** (plain words) · **where** (file / function / class) · **why** (plain words) · **check** (how it is proven).

---

## W-001 Repo, tooling and import-rule lint (Done)

**What.** An empty but working project: eight Python packages, one command that checks everything, CI that runs it, and a rule that stops code importing "upward".

| Piece | Where | Why, in plain words |
|---|---|---|
| Workspace root | `pyproject.toml` (`[tool.uv.workspace]`, `[tool.uv.sources]`) | One repo, one lockfile (`uv.lock`), eight small packages that install together. |
| Eight packages | `packages/<name>/pyproject.toml`, `src/<name>/__init__.py`, `py.typed` | Each job gets its own folder from day one, so boundaries exist before there is code to blur them. `py.typed` lets mypy trust the types across packages. |
| Layer rule | `pyproject.toml` → `[tool.importlinter]`, contract "Imports run down four layers" | Lower layers must not know about higher ones, or the system turns into a tangle. The tool fails the build if someone breaks this. Order: `lake_server \| lake_cli` → `lake_processors \| lake_retrieval` → `lake_ingest \| lake_parsers \| lake_code` → `lake_core`. A `\|` means siblings that may not import each other. |
| One command | `Makefile` targets `lint` (ruff, mypy per package, `lint-imports`) and `test` (lint, then pytest) | Humans, agents and CI all run the same thing, so "passes locally" means "passes in CI". |
| Lint / type config | `pyproject.toml` → `[tool.ruff]` (line 100, rules E,F,I,B,UP), `[tool.mypy]` strict, `[tool.pytest.ini_options]` | Strict typing early is cheap; adding it later is painful. |
| CI | `.github/workflows/ci.yml` | Runs `make test` on every push to main. |
| Agent instructions | `AGENTS.md` (`CLAUDE.md` is a symlink to it) | One file tells any coding agent the commands, layer rules and how to pick up an item. |
| Work tracking | `docs/work/items.csv`, `docs/work/W-001..W-008.md`, `docs/adr/` | Items and status live in git so progress can be diffed. |
| Placeholder dirs | `schemas/`, `config/`, `workers/gpu/`, `deploy/{local,stage-b,stage-c}`, `evals/{golden,fixtures,runs}` (each with `.gitkeep`) | Matches the folder structure in `docs/architecture.md`; later items fill them. |

**Check.** `tests/test_import_rules.py`:
- `test_repo_obeys_layers` runs `lint-imports` on the real repo and expects success.
- `test_upward_import_fails` runs it on a deliberately broken sample (`tests/fixtures/badpkg/{high,low}.py`, config `tests/fixtures/bad.ini`) and expects failure. This proves the rule can actually catch a violation, so a green result means something. Ruff skips `tests/fixtures`, since the bad import is on purpose.

**Not built (on purpose).** No database, no code inside the packages yet. That starts at W-002/W-003.

---

## W-002 Local stack: Postgres with pgvector, object store (Done)

**What.** The two stores the lake needs, runnable on one machine, plus a script that proves both are reachable and usable.

| Piece | Where | Why, in plain words |
|---|---|---|
| Stack definition | `compose.yaml` (services `postgres` = `pgvector/pgvector:pg16`, `minio`) | One file starts both stores. Ports bind to `127.0.0.1` only, so nothing is exposed. Data goes under `LAKE_DATA_DIR` (default `./.data`, git-ignored area) so it is easy to move or back up. |
| Start / stop | `Makefile` targets `up`, `down`, `check-stack` | `make up` waits until Postgres is healthy. |
| Proof script | `deploy/local/check_stack.py` → `main()` | Enables the `vector` extension, checks it is on, creates the bucket if missing. Idempotent, so safe to re-run. |
| CI database | `.github/workflows/ci.yml` → `services.postgres` | Tests need a real Postgres with pgvector; mocks would not catch SQL mistakes. |
| Dev deps | `pyproject.toml` → `dev` group: `psycopg[binary]`, `boto3`, `moto[server]` | psycopg talks to Postgres, boto3 to any S3 store, moto fakes S3 in tests. |

**Check.** `tests/test_stack.py::test_check_stack_script` runs the script against a real Postgres (URL from `LAKE_DATABASE_URL`, default `postgresql://lake:lake@localhost:5432/lake`) and an in-process fake S3 (moto), and expects the success line.

**Honest limits.** This sandbox has no Docker daemon, so `compose.yaml` and `make up` were written but not run here; the script and the Postgres+pgvector side were verified against a native Postgres 16 install, and the S3 side only against moto, not real MinIO. Run `make up && make check-stack` once on your machine to confirm.

---

## W-003 lake_core: settings, db session, migrations (Done)

**What.** The shared foundation every other package builds on: configuration, a way to talk to the database, and schema versioning.

| Piece | Where | Why, in plain words |
|---|---|---|
| Settings | `packages/lake_core/src/lake_core/settings.py` → `Settings`, `load_settings()` | One typed object holds database URL and S3 details. Required values have no default, so a missing one stops the program at startup instead of failing later. Order of precedence: explicit args, environment (`LAKE_*`), then `config/lake.toml`. This is the only file allowed to read the environment. |
| Database | `lake_core/db.py` → `make_engine()`, `make_session_factory()`, `upgrade_to_head()` | One place creates connections and runs migrations, so no other package needs to know how. `expire_on_commit=False` keeps objects usable after a commit. |
| Migrations | `lake_core/migrations/` (`env.py`, `script.py.mako`, `versions/0001_empty.py`) | Alembic keeps the schema versioned. Revision `0001` is intentionally empty (no tables until W-004). Migrations ship inside the package so any install can run them. |
| Test database | `tests/conftest.py` → fixture `db_url` | Each test gets a fresh throwaway database that is dropped afterwards, so tests cannot affect each other. |

**Checks.** `tests/test_core_settings_db.py`: `test_missing_required_settings_fail`, `test_env_overrides_toml`, `test_fresh_db_upgrades_to_head`, `test_only_lake_core_reads_environment` (greps all packages for `os.environ`/`getenv`; only `settings.py` may match).

**Note.** Settings read a `config/lake.toml` file rather than the YAML files listed in the folder structure; those YAML files (`rules.yaml`, `sources.yaml`) are rules data and arrive with the classifier (W-021).

---

## W-004 lake_core: schema v1 (Done)

**What.** The seven "spine" tables, the rules for building IDs, and the two JSON contracts (manifest and job).

| Piece | Where | Why, in plain words |
|---|---|---|
| Tables | `lake_core/migrations/versions/0002_spine.py` (`SQL`): `source`, `content`, `location`, `package`, `chunk`, `embedding`, `job` | Follows the data model. `content` is keyed by file hash, so identical files are stored and processed once; `location` records every place a file was seen. |
| One canonical package | unique partial index `one_canonical_package` on `package(content_sha256) WHERE canonical` | A document may have many revisions but only one is "current". The database enforces it, not application code. |
| One job per work unit | `job` `UNIQUE (processor, version, target)` | Asking for the same work twice cannot create duplicates; this is what makes reruns safe. |
| Search columns | `chunk.tsv` (generated tsvector + GIN index), `embedding.vec vector(384)` + HNSW index | Keyword and meaning search both live in Postgres. 384 dimensions is an assumption (small local model); changing the model means a new migration and re-embedding, which is allowed because derived data is rebuildable. |
| ID rules | `lake_core/ids.py` → `content_sha256`, `location_id`, `package_id`, `chunk_id`, `job_id` | IDs come from content, so a rebuild produces the same IDs. `location_id` includes the content hash, so an edited file at the same path becomes a new row. |
| Contracts | `schemas/manifest.schema.json`, `schemas/job.schema.json`; `lake_core/schemas.py` → `validate_manifest`, `validate_job` | Anything that writes a package or job is checked against a written contract. Schemas are found relative to the checkout (see the `ponytail:` comment). |

**Checks.** `tests/test_core_schema.py`: `test_one_content_row_per_hash`, `test_one_canonical_package_per_content`, `test_one_job_per_processor_version_target`, `test_ids_are_stable`, `test_schemas`.

**Not built.** Satellite tables (label, group, edge, symbol): later items add them as needed.

---

## W-005 lake_core: object store and package IO (Done)

**What.** A small client for the S3-style store, and the functions that save and load originals and packages.

| Piece | Where | Why, in plain words |
|---|---|---|
| Client | `lake_core/objectstore.py` → `ObjectStore` (`put`, `get`, `exists`, `ensure_bucket`) | Wraps boto3 so the rest of the code never touches S3 details; swapping MinIO for another S3 store is a settings change. |
| Key layout | `original_key()`, `package_prefix()` | `originals/<first 2 hex>/<hash>` and `packages/<hash>/<rev>/<file>` exactly as in the runtime layout. The 2-letter folder keeps listings small. |
| Originals | `put_original()`, `get_original()` | Raw bytes saved by hash. Same hash means same bytes, so saving twice is harmless. |
| Packages | `write_package()`, `read_package()`, `PackageExists` | Validates the manifest first, refuses an existing `rev` (packages are immutable), writes the files first and `manifest.json` last, so a half-written package never looks complete. |

**Checks.** `tests/test_core_objectstore.py`: `test_round_trip_byte_for_byte`, `test_existing_rev_rejected_new_rev_ok`, `test_bad_manifest_rejected_and_nothing_written` (runs against in-process moto S3).

**Known limit.** The "does this rev exist" check and the write are two steps, fine with one writer (see the `ponytail:` comment in `write_package`).

---

## W-006 Registrar (Done)

**What.** The single doorway for new files. Every source type ends here, so duplicate detection and first-job creation exist once.

| Piece | Where | Why, in plain words |
|---|---|---|
| Item and adapter shape | `packages/lake_ingest/src/lake_ingest/adapter.py` → `Item`, `Adapter` | An adapter only finds files and hands over bytes, a path, and a source name. It never touches the database. |
| Registrar | `lake_ingest/registrar.py` → `Registrar.register()` returns `Result(content_sha256, new_content, new_location)` | One transaction: record source, content, location. Inserts use `ON CONFLICT DO NOTHING`, so the same bytes at two paths give one content row and two location rows, and the same path twice changes nothing. |
| New content only | inside `register()` | Original bytes are stored and the first job is enqueued only when the content is new, so re-adding a folder does no repeat work. |
| Type detection | `detect_type()`, `SUFFIX_TYPES` | Cheap guess from the file suffix, unless the adapter gave a hint. Smarter detection arrives with W-021. |
| Markdown shortcut | `Registrar._write_markdown_package()` | If the adapter already has markdown (a note, a chat), the package is written immediately and the first job is `chunk`. Binary files (PDF etc.) get a `parse` job instead and the parse processor writes their package (resolves the open question in the build-order doc). |
| Job creation | `Registrar._enqueue()` | Job id comes from processor + version + target, so enqueueing twice is a no-op. |

**Checks.** `tests/test_registrar.py`: `test_same_bytes_two_paths_and_same_path_twice`, `test_markdown_item_gets_package_and_chunk_job`. Test helpers in `tests/conftest.py` (`db_url`, `store`).

---

## W-007 Job loop and processor contract (Done)

**What.** The engine that runs all background work: workers take jobs from a Postgres table, one at a time, safely.

| Piece | Where | Why, in plain words |
|---|---|---|
| Contract | `packages/lake_processors/src/lake_processors/contract.py` → `Processor` (protocol), `Context(engine, store)`, `Registry` | A processor is a small class with a name, a version and `run(target, ctx)`. Bumping `version` makes new job rows, so everything is reprocessed. Signature differs from the first architecture draft, see `docs/adr/0001-processor-run-signature.md`. |
| Claiming | `lake_processors/loop.py` → `CLAIM` SQL, `claim()` | One statement picks a ready job with `FOR UPDATE SKIP LOCKED` and marks it running with a lease. Two workers can never get the same job, with no extra coordination or broker. |
| Crash recovery | same `CLAIM` (`status='running' and lease_until < now()`) | If a worker dies, its lease runs out and the job becomes claimable again. |
| Retry and dead letter | `finish()` | Failure puts the job back with a growing delay (`backoff * 2^(attempts-1)`); after `max_attempts` it is marked `dead` and keeps its last error for a human to read. |
| Running | `run_once()`, `run_until_idle()` | Exceptions from a processor are caught and recorded by the loop, so processors stay simple. |

**Checks.** `tests/test_job_loop.py`: `test_two_workers_never_claim_the_same_job`, `test_crashed_workers_lease_expires_and_job_reruns`, `test_always_failing_processor_ends_dead`, `test_rerun_creates_no_duplicates`.

**Not built.** The GPU branch (`cost: gpu` currently runs like any other job). `architecture.md` updated for the changed signature.

---

## W-008 Upload adapter and `lake add` (Done)

**What.** The first way to put things in the lake: `lake add <file-or-folder>`.

| Piece | Where | Why, in plain words |
|---|---|---|
| Upload adapter | `packages/lake_ingest/src/lake_ingest/upload.py` → `UploadAdapter.scan()` | Walks a file or folder (sorted, so runs are repeatable) and yields `Item`s. `.md` and `.txt` files are handed over as markdown so they skip parsing. No ignore rules yet (W-020). |
| CLI | `packages/lake_cli/src/lake_cli/main.py` → `add()`, `main()`; command `lake` declared in `packages/lake_cli/pyproject.toml` | Loads settings, builds the registrar, feeds it, prints counts such as `2 files, 0 new content, 0 new locations`. |

**Checks.** `tests/test_cli_add.py`: `test_add_folder_twice_reports_no_new_content`, `test_add_single_file_end_to_end` (real Postgres with pgvector, moto S3).

**Honest limit.** "Stage A stack" here means native Postgres + fake S3, since Docker is unavailable in this sandbox. Run `make up` on your machine and then `lake add` with the `LAKE_*` variables to confirm against MinIO.

---

## W-009 Docling parse processor (Done, with a gap)

**What.** The step that turns an uploaded PDF (or other binary) into a markdown package and queues chunking.

| Piece | Where | Why, in plain words |
|---|---|---|
| Parser interface | `packages/lake_parsers/src/lake_parsers/base.py` → `Parser`, `Parsed` | Every parser (Docling now, MinerU later) returns the same thing: markdown, structure, assets, QA info. Swapping a parser never touches the rest. |
| Docling backend | `lake_parsers/docling_backend.py` → `DoclingParser.parse()` | Default parser. Imported only when used because it is heavy. Optional install: `lake-parsers[docling]`. |
| Plain fallback | `lake_parsers/plain.py` → `PlainTextParser` | Reads text as is. Used as the fallback and as the test stand-in. |
| Parse step | `packages/lake_processors/src/lake_processors/parse.py` → `ParseProcessor.run()` | Loads the original, picks a parser by source type, writes package rev 1 (`content.md`, `structure.json`, assets, manifest), inserts the canonical package row, queues a `chunk` job. If a package already exists it only re-queues chunking, so reruns add nothing. |
| Shared job helper | `packages/lake_core/src/lake_core/jobs.py` → `enqueue_job()` | Moved down from the registrar so both packages share it (layer rule). |

**Checks.** `tests/test_parse_processor.py::test_parse_writes_package_and_queues_chunk` (with the plain parser). `tests/test_docling_smoke.py` runs real Docling on `tests/fixtures_data/sample.pdf`.

**Gap, honestly.** In this sandbox Docling installs but cannot download its model weights (Hugging Face is blocked), so the smoke test **skips here** and the Docling backend has not been run end to end. Run `uv sync --extra docling` (or `pip install docling`) on your machine and `uv run pytest tests/test_docling_smoke.py` to confirm; if the output shape differs, fix `DoclingParser.parse()` only.

---

## W-010 Chunk processor (Done)

**What.** Cuts a package's markdown into passages that can be searched and cited.

| Piece | Where | Why, in plain words |
|---|---|---|
| Splitter | `packages/lake_processors/src/lake_processors/chunk.py` → `split_markdown()`, `Piece`, `MAX_CHARS=1200` | Splits at headings, keeps the heading path (`Book > Ch1`) as the section so citations can point somewhere readable, packs paragraphs up to 1200 characters, and does not treat `#` lines inside code fences as headings. |
| Processor | `ChunkProcessor.run()` | Reads `content.md`, writes chunk rows (id from package + position + chunker version, `ON CONFLICT DO NOTHING` so reruns add nothing), queues an `embed` job. |

**Checks.** `tests/test_chunk.py`: `test_split_tracks_heading_path_and_respects_limit`, `test_chunk_job_writes_rows_once_and_queues_embed`.

**Choice to review.** 1200 characters is a starting size, not tuned; retrieval evals (W-014) should decide.

**Fix made during W-010.** The registrar (W-006) queued the markdown shortcut's `chunk` job with a content hash, but `chunk` targets a package id (`<hash>:<rev>`). Caught by the W-010 end-to-end test; fixed in `Registrar.register()` and covered by `tests/test_registrar.py::test_markdown_chunk_job_targets_the_package`. Job targets are: `parse` → content hash; every later step → package id.

---

## W-011 Embedding and full-text index (Done, real model unverified)

**What.** Makes every chunk findable by meaning (vectors) and by words (full-text).

| Piece | Where | Why, in plain words |
|---|---|---|
| Embedder interface + implementations | `packages/lake_core/src/lake_core/embedding.py` → `Embedder`, `HashEmbedder`, `BgeSmallEmbedder`, `make_embedder()`, `to_pgvector()` | Documents (processors) and questions (retrieval) must use the *same* model, and those two packages cannot import each other, so the embedder lives in `lake_core`. `HashEmbedder` is offline and deterministic (word overlap only) for tests and no-download use. `BgeSmallEmbedder` (bge-small, 384 dims) is the real default. |
| Setting | `lake_core/settings.py` → `Settings.embedder` (default `bge-small`, or `hash`) | Choose the model without code changes. |
| Embed step | `packages/lake_processors/src/lake_processors/embed.py` → `EmbedProcessor.run()` | Embeds only chunks that have no vector for this model yet, in batches of 64. `version` is the model name, so switching model creates new jobs and re-embeds everything. |
| Full-text | `chunk.tsv` generated column + `chunk_tsv` GIN index (W-004 migration) | Postgres keeps it up to date by itself, so no processor is needed. |

**Checks.** `tests/test_embed.py::test_embed_and_full_text`: vector search ranks the right chunk first, full-text finds the other, rerun adds no rows.

**Gap.** `BgeSmallEmbedder` needs `sentence-transformers` and a model download (blocked in this sandbox), so it is untested here. Install with `pip install sentence-transformers` on your machine; until then use `LAKE_EMBEDDER=hash` (search is word-overlap only).

---

## W-012 Hybrid search, fusion and citations (Done, no reranker)

**What.** One function that takes a question and returns the best passages with proof of where each came from.

| Piece | Where | Why, in plain words |
|---|---|---|
| Search | `packages/lake_retrieval/src/lake_retrieval/search.py` → `search()` | Runs two searches (meaning via vectors, words via full-text), each already limited by the filters, takes 50 candidates from each, merges them, and returns the top passages. |
| Filters first | `Filters`, SQL fragment `_BASE` | Source type and trust tier cut the candidate set *before* ranking, so a filtered search still returns a full list. Only canonical packages are searched. |
| Fusion | `rrf()` (reciprocal rank fusion, k=60) | A passage ranked well by both searches beats one ranked top by only one, and no score scaling is needed between the two. |
| Citation | `make_uri()`, `slug()`, `Passage.citation` | `lake://<hash>#<rev>/<section-slug>`, title, section, file location and tier, matching the architecture's citation format. |
| Budget | `max_chars` parameter | Stops adding passages once the character budget is used (always keeps at least one). Characters stand in for tokens for now. |

**Checks.** `tests/test_search.py`: `test_rrf_rewards_agreement`, `test_hybrid_search_returns_cited_passages`, `test_filters_cut_candidates_before_search`, `test_token_budget_trims`.

**Not built.** The rerank step and graph expansion: the architecture lists rerank, but it needs a model download; add it behind a `Reranker` protocol once the eval set (W-014) shows it is needed.

---

## W-013 MCP server: search and fetch (Done)

**What.** Agents can now ask the lake questions over MCP.

| Piece | Where | Why, in plain words |
|---|---|---|
| Tool logic | `packages/lake_server/src/lake_server/mcp_tools.py` → `search_json()`, `fetch_json()` | Plain functions, so they are testable without a network. `search` returns evidence only (passages + citation URI, tier, location, score), never a written answer. `fetch` takes a `lake://` URI from `search` and returns that section's full text (or the whole document if the URI has no section). Bad URIs raise a clear error. |
| Server | `create_server()` → `MCPServer("knowledge-lake")` with exactly two tools, `search(query)` and `fetch(id)` | One string argument each, which is the shape ChatGPT connectors require; Claude and Codex also accept it. Richer tools arrive in W-019. |
| App | `lake_server/app.py` → `build_app()` (ASGI, path `/mcp`) | Streamable HTTP, bound to localhost by `lake serve`. |
| Command | `lake_cli/main.py` → `lake serve` | Starts it with uvicorn on 127.0.0.1:8000. |

**Checks.** `tests/test_mcp_server.py`: `test_search_then_fetch_round_trip`, `test_fetch_rejects_bad_ids`, `test_server_exposes_exactly_search_and_fetch_over_mcp` (calls the tool through the MCP server object).

**Not built.** Auth and scopes (W-032), so `serve` is localhost-only for now. The MCP SDK installed is 2.x (`mcp.server.mcpserver.MCPServer`), whose API differs from the 1.x `FastMCP` in most online examples. The HTTP transport was checked by hand with the MCP client against a running `uvicorn` (tools listed correctly); automated tests call the server object instead.

**Walking skeleton closed (W-001 to W-013).** `lake_cli/main.py` also gained `lake work` (`work()`, `build_registry()`: runs parse, chunk and embed jobs, using Docling for pdf/docx/html/epub only if it is installed, else the plain parser). `tests/test_end_to_end.py::test_add_work_search_fetch` runs add, work, search and fetch in one test.

---

## W-014 Golden question set and eval runner (Done)

**What.** A fixed set of questions with known answers, and a script that scores search against them, so changes to chunking, embedding or ranking can be judged by numbers.

| Piece | Where | Why, in plain words |
|---|---|---|
| Fixture documents | `evals/fixtures/docs/*.md` (raft, postgres, bread, hiking) | Small, unrelated documents, so a wrong answer is clearly wrong. |
| Golden set | `evals/golden/questions.jsonl` (8 questions; each names the document and a phrase the right passage must contain) | A question counts as answered only if a returned passage comes from the right document *and* contains the phrase. |
| Runner | `evals/run_eval.py` → `evaluate()`; run `python evals/run_eval.py --embedder hash` | Ingests the fixtures, runs jobs, asks every question, computes recall@5 and MRR (average of 1/rank), writes `evals/runs/<time>-<embedder>.json`. Use a scratch database. |

**Checks.** `tests/test_eval_runner.py::test_eval_runner_scores_golden_set` requires recall@5 ≥ 0.75 with the offline hash embedder. Measured: recall@5 = 1.00, MRR = 0.91.

**Caveat.** The set is tiny and easy, so it catches breakage, not subtle quality differences. Grow it from your real documents; the real-embedder score is still to be recorded on your machine.

---

## W-015 GUI v1: browse, search, reader (Done)

**What.** A private web page where you can walk the lake, search it and read documents. Read-only for now.

| Piece | Where | Why, in plain words |
|---|---|---|
| Routes | `packages/lake_server/src/lake_server/gui.py` → `build_gui_routes()`: `/login`, `/logout`, `/` (browse), `/search`, `/doc/{sha}` | Server-rendered pages calling the same `search()` the MCP tools use, so you and agents see identical results. |
| Login | `gui.py` → `login()`, `guard()`; setting `LAKE_GUI_PASSWORD` in `lake_core/settings.py` | One password, compared in constant time, stored in a signed session cookie. The GUI is **off** unless the password is set. |
| Browse | `browse()` | Walks the stored file paths like folders (`?path=/notes`), showing sub-folders and documents with their titles. |
| Reader | `doc()`, `render_markdown()` | Renders `content.md`; heading ids use the same slug as citation URIs, so a search hit links straight to its section (`/doc/<hash>#databases-replication`). Shows outline, versions and locations. |
| Safety | `MarkdownIt("commonmark", {"html": False})` | Raw HTML inside documents is escaped. The test caught that the library's default would have let `<script>` through. |
| Templates | `packages/lake_server/src/lake_server/templates/*.html` | Plain HTML and a little CSS; no JavaScript build step. |
| Wiring | `lake_server/app.py` → `build_app()` | GUI routes plus MCP at `/mcp` in one app; run with `lake serve`. |
| Titles | `lake_core/titles.py` → `title_from_markdown()` (used by registrar and parse step) | Documents show their first heading as title instead of the file name. |

**Checks.** `tests/test_gui.py`: `test_requires_login`, `test_browse_search_read`, `test_render_markdown_ids_match_citation_slugs`.

**Deviations / not built.** HTMX is not used yet (plain links and forms are enough for v1). No page-image viewer, links-in/out (needs W-017), editing or review queue (W-023). `lake serve` needs `LAKE_S3_*` and `LAKE_GUI_PASSWORD`.

---

## W-016 Website crawler adapter (Done)

**What.** `lake crawl <url>` pulls a documentation site into the lake.

| Piece | Where | Why, in plain words |
|---|---|---|
| Crawler | `packages/lake_ingest/src/lake_ingest/crawl.py` → `CrawlAdapter.scan()` | Breadth-first from the start page. Stays under the start URL's folder (`same_prefix`), obeys `robots.txt`, limits pages (100) and depth (3), pauses 0.5 s between requests, skips non-HTML and error pages, ignores `#fragments`. |
| Conversion | same file, BeautifulSoup + `markdownify` | Drops scripts, styles, nav and footer, converts to markdown, and adds the page `<title>` as a heading when there is none, so titles and citations work. Items carry the raw HTML as the original and the markdown ready-made (so no parse step). |
| Command | `lake_cli/main.py` → `lake crawl <url>`; `add()` now takes any adapter | Same counting output as `lake add`; re-crawling reports no new content for unchanged pages. |

**Checks.** `tests/test_crawler.py`: `test_crawl_stays_in_prefix_obeys_robots_and_makes_markdown`, `test_page_limit` (against a local HTTP server).

**Limits.** Static HTML only (no JavaScript rendering). The sandbox cannot reach the open web, so only the local test server was crawled. Pages redirected to a different URL are recorded under their final URL.

---

## W-017 Deterministic link graph (Done)

**What.** Records which document links to which, using only explicit links (no AI guessing), and shows them in the reader.

| Piece | Where | Why, in plain words |
|---|---|---|
| Table | `lake_core/migrations/versions/0003_edge.py` → `edge(src_sha, dst_ref, dst_sha, kind, anchor)` | One row per distinct link. `dst_sha` stays empty until the target is in the lake. |
| Extraction | `packages/lake_processors/src/lake_processors/link.py` → `LinkProcessor.run()`, `MD_LINK`, `resolve_ref()` | Finds markdown links, makes relative ones absolute against where the source file lives (file path or URL), drops `mailto:`, `#fragment`-only and similar. |
| Late resolution | last statement of `run()` | Every run also fills in any still-open links whose target has since arrived, so adding files in any order gives the same graph. |
| Wiring | `ChunkProcessor.run()` queues `link`; `lake_cli.build_registry()` registers it | Links are found right after chunking. |
| Reader | `lake_server/gui.py` → `doc()` plus `templates/doc.html` | "Links out" and "Linked from" lists. |

**Checks.** `tests/test_link.py`: `test_resolve_ref`, `test_links_resolve_even_when_target_arrives_later`; `tests/test_gui.py` now checks the link sections.

**Limits.** Markdown inline links only (not reference-style `[x][1]`, bare URLs or HTML `<a>` in non-crawled files). Package-level edges for older revisions are not tracked; links belong to the content.

---

## W-018 QA scoring and MinerU escalation (Done in code, GPU worker unverified)

**What.** After parsing, the result is checked; if it looks bad, a stronger parser (MinerU on a rented GPU) is tried, and anything still doubtful is flagged for review.

| Piece | Where | Why, in plain words |
|---|---|---|
| QA scoring | `packages/lake_parsers/src/lake_parsers/qa.py` → `score()` | Cheap checks: empty output; garbled characters (more than 2% replacement/control characters); far too little text for a big PDF/DOCX/EPUB (a failed scan). Returns `ok`, `reasons`, counts. |
| Escalation | `lake_processors/parse.py` → `ParseProcessor(..., escalation=...)` | Runs QA after the first parse. On failure it tries the escalation parser and keeps whichever result is OK or has more text; the manifest `qa` records `escalated_to` and `first_failure`. If escalation errors, the first result is kept with `needs_review: true` and `escalation_error`. Nothing is silently lost. |
| Remote parser | `lake_parsers/remote.py` → `RemoteParser` (`POST {url}/parse`, bearer token) | The main server talks to the GPU box over HTTP; the GPU box never gets database credentials. |
| Settings / wiring | `lake_core/settings.py` → `gpu_url`, `gpu_token`; `lake_cli.build_registry()` | Escalation is on only when `LAKE_GPU_URL` is set. |
| GPU worker | `workers/gpu/app.py`, `workers/gpu/Dockerfile` | FastAPI wrapper that runs the `mineru` command. **Not run or tested**: no GPU, no model access here. Check the MinerU command and output path against the installed version first. |

**Checks.** `tests/test_qa_escalation.py`: `test_qa_flags_empty_garbled_and_sparse_output`, `test_failed_qa_escalates_to_stronger_parser`, `test_escalation_failure_keeps_first_result_flagged`, `test_remote_parser_posts_file_and_reads_markdown` (local HTTP stub).

**Open items from the architecture.** MinerU licence still needs reading before real use (open question in `architecture.md`). The "review queue" that lists `needs_review` packages arrives with W-023.

---

## W-019 Remaining read tools (Done)

**What.** Four more MCP tools so agents can narrow searches and explore around a document.

| Tool | Where (all in `packages/lake_server/src/lake_server/mcp_tools.py`) | Plain-words behaviour |
|---|---|---|
| `query(query, source_type, tier, limit)` | `query_json()` | Search with filters; limit capped at 50. |
| `get_document(id)` | `get_document_json()` | Manifest, the outline (section names in reading order) and all revisions. `id` can be a hash or a `lake://` URI. |
| `neighbors(id, limit)` | `neighbors_json()` | Links out, documents that link here, and *similar* documents: the average vector of this document compared with the closest chunk in every other document. |
| `resolve_source(id)` | `resolve_source_json()` | Every source and path where the same bytes were found, with times. |

**Checks.** `tests/test_mcp_server.py`: `test_read_tools`, `test_neighbors_finds_similar_document`, and the tool-list test now expects six tools.

**Not yet.** Label and group filters in `query` (they arrive with W-021). Scopes are still not enforced (W-032): every tool here is a `read` tool. `research` is W-030; code tools W-025.

---

## W-020 Disk walker and ignore rules (Done)

**What.** `lake disk <folder>` walks a whole folder tree (read-only) and indexes only what is worth indexing, with a clear reason for everything skipped.

| Piece | Where | Why, in plain words |
|---|---|---|
| Walker | `packages/lake_ingest/src/lake_ingest/disk.py` → `DiskAdapter.scan()`, `.skipped` | Walks depth-first in sorted order, never writes. Skips symlinks, empty files and files over 200 MB, and records `(path, reason)` for each skip. An ignored folder is not entered at all. |
| Rule layers | `DiskAdapter._layers()`, `_why()` | Three layers in gitignore syntax: built-in defaults (`config/lakeignore.default`), your `<root>/.lakeignore`, and every `.gitignore` found in the tree (applies below its own folder). The last matching layer wins, and `!pattern` can re-include. |
| Explanations | `DiskAdapter.decide(root, path)` → `Decision(ignored, reason)` | Answers "why was this skipped?" including parent-folder ignores, e.g. `default rules: .venv/`. W-022 exposes it as a tool. |
| Defaults | `config/lakeignore.default` | Dependency folders, VCS internals, caches, OS junk, binaries (`.exe`, `.so`, `.iso`...). |
| Command | `lake_cli/main.py` → `lake disk <path>` | Reads the defaults from the configured `config_dir`; prints counts and how many paths were skipped. |
| Fixture | `evals/fixtures/disk_tree/` | A fake tree with a venv, nested `.gitignore`, `.lakeignore`, an empty file. |

**Checks.** `tests/test_disk_walker.py`: `test_walker_applies_default_lakeignore_and_gitignore_layers`, `test_decide_explains_paths_and_nested_ignores`, `test_size_cap_and_symlinks_skipped`.

**Limits.** Files are read whole into memory (hence the size cap). Secrets and credentials are not detected yet: that is the secret scan in W-027, and until then do not point `lake disk` at a home folder that holds keys. The skipped list is printed as a count only; it is not stored in the database.

---

## W-021 Dedupe, type detection, classify and group (Done, subset of Req 6)

**What.** Files get a trustworthy type, labels, and suggested groupings (duplicates, versions, near-copies) without anything being moved or renamed.

| Piece | Where | Why, in plain words |
|---|---|---|
| Exact dedupe | already the registrar (W-006); `GroupProcessor` records an accepted `exact_duplicate` group when one content has several locations | One document in many places is parsed once; the group makes it visible. |
| Type detection | `packages/lake_ingest/src/lake_ingest/types.py` → `detect_type()`, `sniff()` | Unambiguous signatures (PDF, PNG, JPEG, GIF) win over extensions; plain-text suffixes are trusted for text; everything else goes to Google's Magika model (runs offline on CPU). Used by the registrar. |
| Label tables | `lake_core/migrations/versions/0004_labels_groups.py` → `label`, `doc_group`, `doc_group_member` | A label is `(file, key, value, source, confidence)`; sources are `manual`, `rule`, `folder`, `content`. Groups are computed rows with a status (`suggested`/`accepted`/`rejected`) for the review screen. |
| Classification | `packages/lake_processors/src/lake_processors/classify.py` → `ClassifyProcessor`, `load_rules()`, `effective_labels()`; rules in `config/rules.yaml` | Adds the detected type (content), the parent folder name (folder, low confidence) and any matching path rule. `effective_labels()` (now in `lake_core/labels.py`, re-exported by `classify.py`) picks per key by precedence manual > rule > folder > content. The upsert never overwrites a `manual` row. The processor version includes a hash of the rules, so editing `rules.yaml` re-runs classification. |
| Grouping | `lake_processors/group.py` → `GroupProcessor`, `family_key()` | **Version families:** same folder, same file name after removing words like `v2`, `final`, `copy`, `(2)`, dates. **Near-duplicates:** documents whose average vectors are within cosine distance 0.1. Both are *suggestions*. Queued after embedding. |
| Wiring | `ChunkProcessor` queues `classify`; `EmbedProcessor` queues `group`; `lake_cli.build_registry(..., rules_yaml)` | |

**Checks.** `tests/test_classify_group.py`: `test_type_detection_trusts_content_for_binaries`, `test_family_key_ignores_version_words`, `test_labels_follow_rules_and_manual_wins` (manual survives a rerun), `test_groups_exact_duplicates_families_and_near_duplicates`.

**Not built from Req 6 (be aware):** perceptual-hash image duplicates, EXIF/metadata extraction, project bundles, photo events, topic clusters, backup lineages, partial-hash dedupe before reading (the walker reads whole files), repo-root routing to the code indexer. Near-duplicate quality depends on the real embedder; the 0.1 threshold was tested only with the hash embedder. Label and group filters in `query` are not wired yet (use `effective_labels()` / SQL).

---

## W-022 explain_path tool (Done)

**What.** Answers "why wasn't this indexed?" or "why is it labelled this way?", from the command line and over MCP.

| Piece | Where | Why, in plain words |
|---|---|---|
| Logic | `packages/lake_ingest/src/lake_ingest/explain.py` → `explain_path_json()` (lives in `lake_ingest` so both the server and the CLI can use it without importing each other) | Looks the path up in the catalog (indexed? type? effective labels), and for paths under a known disk root re-runs the walker's rules (`DiskAdapter.decide`) to give the exact rule that ignored it, such as `default rules: .venv/`. Unknown paths say so instead of guessing. |
| Disk roots | `record_disk_root()`, `disk_roots()` (stored in `source.config.roots` for source `disk`) | The ignore rules depend on which folder was walked, so `lake disk` remembers its roots. |
| MCP tool | `mcp_tools.py` → `explain_path(path)` | Marked admin-only; **scope enforcement arrives in W-032**, so until then do not expose the server beyond localhost. |
| CLI | `lake_cli/main.py` → `lake explain <path>` | Prints the same JSON. |

**Checks.** `tests/test_explain_path.py`: `test_explain_indexed_and_ignored_paths`, `test_cli_explain_prints_json`; tool list test updated (seven tools).

**Limit.** Per-subtree skip rows and the "largest ignored subtrees" report from the plan are not stored (skips are recomputed on demand).

---

## W-023 GUI review queue, sources, jobs and markdown editor (Done)

**What.** The GUI can now change things (always as new rows, never by editing history): review suggestions, manage sources and failed jobs, edit and create markdown, set labels.

| Screen / route | Where | Why, in plain words |
|---|---|---|
| Editor `GET/POST /doc/{sha}/edit`, `POST /preview` | `packages/lake_server/src/lake_server/gui.py`; logic in `lake_server/edit.py` → `save_revision()`, `current_markdown()`; template `templates/edit.html` | Plain textarea beside a live preview (a few lines of inline JavaScript call `/preview`, which renders with the same server-side renderer as the reader). Saving writes the **next revision** (`tier: derived`, `edited_by: gui`), makes it the canonical one and queues re-chunking for that document only. Revision 1 stays recoverable. |
| New note `GET/POST /new` | `new_page()` | Registers a markdown item under source `gui` via the normal registrar, so notes get chunked, embedded, linked and classified like anything else. |
| Labels `POST /doc/{sha}/label` | `edit.py` → `set_manual_label()` | Saves a `manual` label, which wins over rules and is never overwritten by later runs. |
| Review `GET /review`, `POST /review/group/{id}/accept|reject` | `lake_server/admin.py` → `review_items()`, `decide_group()` | Lists suggested groups (duplicates, version families) and parses flagged `needs_review`; accept/reject only changes the group's status. |
| Sources & jobs `GET /jobs`, retry, add path, crawl | `admin.py` → `jobs_overview()`, `retry_job()`; `gui.py` → `add_path()`, `crawl()` | Shows queue counts by processor and status, failing/dead jobs with Retry (resets attempts), sources with counts. "Add" walks a server-side path with the disk rules; "Crawl" runs the crawler in a background thread. |

**Checks.** `tests/test_gui.py`: `test_edit_makes_new_derived_revision_and_old_one_stays`, `test_new_note_review_jobs_and_labels`, `test_group_decision_and_job_retry` (plus the earlier login/browse/search/reader tests).

**Limits / to know.**
- Saved edits are searchable only after a worker runs (`lake work`) re-chunks and re-embeds the new revision.
- The crawl runs inside the web process thread with no progress display; "Add path" runs inside the request and can be slow for large trees.
- No quarantine release screen yet (needs W-027's secret scan). Cookie-based forms rely on the session cookie's `SameSite=Lax`, there is no separate CSRF token.
- Groups accepted in review are not yet used as search filters.

---

## W-024 Code adapter and symbols (Done)

**What.** `lake code <repo>` indexes a source repository: every code file gets its definitions extracted, and each definition becomes a searchable chunk.

| Piece | Where | Why, in plain words |
|---|---|---|
| Language map | `packages/lake_core/src/lake_core/languages.py` → `language_of()` | Python, JavaScript, TypeScript/TSX, Go, Rust, Java by suffix. In `lake_core` because both ingest (typing) and the code package need it and may not import each other. |
| Symbol extraction | `packages/lake_code/src/lake_code/symbols.py` → `extract_symbols()`, `Symbol`, `DEFS` | tree-sitter finds functions, classes, methods, interfaces, structs etc. Each symbol has a qualified name (`Repo.save`), kind, one-line signature, docstring (Python) or preceding comment (others), line range and parent. Functions inside classes become methods. |
| Adapter | `packages/lake_ingest/src/lake_ingest/code.py` → `CodeAdapter.scan()`, `wanted()`, `RepoInfo` | In a git repo the file list is exactly what git reports (tracked plus untracked-not-ignored), so `.gitignore` is honoured. Takes code files, manifests (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`...) and `.md` docs; skips `.env`, keys and certificates by name, files over 2 MB. Without git it falls back to the disk ignore rules. |
| Repo tables | `lake_core/migrations/versions/0005_code.py` → `code_repo`, `code_repo_file` (repo, commit, path, content hash), `code_symbol` (+ `pg_trgm` index on names) | Files are indexed per `(repo, commit)` but symbols hang off the content hash, so an unchanged file in a new commit costs nothing and the same file in two repos is parsed once. `record_repo()` writes the repo rows. |
| Indexer | `packages/lake_processors/src/lake_processors/code_index.py` → `CodeIndexProcessor` | Stores the source as a package (fenced code block, so the reader works), writes symbol rows, and one chunk per symbol (`path + doc + body`, 1500 characters max; files with no symbols get their first 60 lines). Then queues embedding and classification. |
| Routing | `Registrar.register()` queues `code_index` (not `parse`) for type `code`; `detect_type()` returns `code` for known suffixes | |

**Checks.** `tests/test_code_index.py`: Python symbols (signature, doc, lines, parents), JS/TS/Go/Rust/Java symbols, JS comment docs, and an end-to-end git repo test (gitignored file and `.env` never reach the lake; symbols, chunks and embeddings exist).

**Not built yet.** Commit history and ownership; indexing only changed files of older copies; "repos duplicated across backups" logic; the full secret scan (W-027). Symbols for other languages (C/C++, Ruby, PHP...) need their tree-sitter grammar added to `DEFS`.

---

## W-025 SCIP references, repo map and code tools (Done, SCIP not integrated)

**What.** Agents can ask code questions: where is X defined, who uses it, what is in this file, show me lines 10-40, give me a map of the repo.

| Piece | Where | Why, in plain words |
|---|---|---|
| References and imports | `packages/lake_code/src/lake_code/symbols.py` → `extract_references()`, `Reference` | Every identifier that is not a definition's own name is recorded as a `call` or `ref` with its line, plus the import statements. **This is name matching, not precise**: two different functions called `save` are not told apart. |
| Tables | `lake_core/migrations/versions/0006_code_refs.py` → `code_ref`, `code_import`, `code_repo_file.seen_at` | `seen_at` lets tools pick the newest indexed commit of each repo. |
| Indexer | `CodeIndexProcessor` (version bumped to `2`) fills the new tables | |
| Tools | `packages/lake_server/src/lake_server/code_tools.py` → `code_search_json`, `find_symbol_json`, `find_references_json`, `file_outline_json`, `get_file_json`, `repo_map_json`; registered in `mcp_tools.create_server()` as `code_search`, `code_find_symbol`, `code_find_references`, `code_file_outline`, `code_get_file`, `code_repo_map` | `find_symbol` accepts qualified names and tolerates near spellings (trigram similarity). `get_file` returns at most 400 lines per call. `repo_map` ranks files by how many *other* files reference their top-level symbols and trims to a character budget (an Aider-style map). `code_search` shows symbol-name matches first, then hybrid search restricted to code. Results say `precision: name match` where relevant. |

**Checks.** `tests/test_code_index.py`: `test_references_and_imports`, `test_code_tools` (two-file repo through `lake code` and `lake work`).

**Deliberately not done.** SCIP indexers (scip-python, scip-typescript, rust-analyzer): they need Node/language toolchains that are not available here. The plan's fallback (tree-sitter) is what runs. When you add SCIP, load its occurrences into `code_ref` with a new `kind` value and keep these tools unchanged. Scope `code:read` is documented but enforced only from W-032. Implementations and inheritance edges are not extracted.

---

## W-026 Docs bridge (Done)

**What.** "How do I use the library this code imports?" Each dependency a repo declares is matched with documentation already in the lake, so an agent can go from code to docs in one call.

| Piece | Where | Why, in plain words |
|---|---|---|
| Manifest reader | `packages/lake_code/src/lake_code/manifests.py` → `parse_manifest()`, `Dependency`, `search_terms()` | Reads `pyproject.toml` (dependencies, dependency groups, optional extras), `requirements.txt`, `package.json`, `Cargo.toml`, `go.mod`. Names are turned into search words (scope and path prefixes dropped: `@scope/lib` → `lib`, `github.com/gin-gonic/gin` → `gin`). |
| Matching | `packages/lake_server/src/lake_server/code_tools.py` → `dependency_docs_json()` | For each dependency, finds non-code documents whose **title** or **URL/path** contains the name as a whole word. Title matches rank above path matches; up to 3 per dependency; dependencies with no docs show an empty list (a hint of what to crawl next). Computed on demand, nothing stored. |
| Tool | `code_dependency_docs(repo)` in `mcp_tools.py` | Scope `code:read`. |
| Manifests as documents | `CodeAdapter` marks them `source_type="manifest"` | They are stored and searchable but excluded from doc matching. |

**Checks.** `tests/test_code_index.py`: `test_manifest_parsing`, `test_dependency_docs_link_to_crawled_documentation`.

**Limits.** Matching is by name only (no package-registry lookup of the official docs URL), so very short or generic names (`click`, `rich`) can match unrelated pages. Lockfiles (resolved versions) are not read. Docs are not version-matched to the pinned version.

---

## W-027 Chat importers, write-back tools and secret scan (Done; export formats unverified)

**What.** Conversations and agent-written documents can enter the lake, and secrets are caught before anything is stored or indexed.

| Piece | Where | Why, in plain words |
|---|---|---|
| Secret scanner | `packages/lake_core/src/lake_core/secrets.py` → `scan()`, `redact()`, `Finding`, `PATTERNS` | Regexes for AWS keys, GitHub/Slack/Google/Stripe/LLM-provider keys, private-key blocks, JWTs, and generic `password=`/`token:` assignments (only if the value looks random, entropy ≥ 3.5). Findings carry kind and line, never the secret. |
| Quarantine | `lake_ingest/registrar.py` → `Registrar.register()` (scan step), `Registrar.release()`; table `quarantine` (`0007_quarantine.py`); `lake_ingest/quarantine.py` → `held()` | A text file with a secret is **not indexed**: its bytes go to `quarantine/<hash>` (never `originals/`), content type becomes `quarantined`, no package and no jobs. Review shows what was found; **Release** stores it normally and starts jobs. Binary types (PDF, images...) are not text-scanned. |
| Chats redact instead | `Item.on_secrets="redact"` | A conversation is too valuable to drop: secrets are replaced by `[REDACTED:kind]` before hashing and storing, and the manifest lists `redacted`. |
| Derived tier | `Item.tier`, `Item.title`, `Item.meta` (merged into the manifest); registrar writes `tier: derived` to manifest and `package.tier` | Chats and generated documents are marked model output, so search results can flag or filter them (`tier`). |
| Export importers | `lake_ingest/chat.py` → `ClaudeExportAdapter`, `ChatGPTExportAdapter`, `ClaudeCodeAdapter`, `render_conversation()` | Claude.ai `conversations.json` (folder, file or zip), ChatGPT `conversations.json` (follows the final branch of the message tree, so discarded drafts are skipped), Claude Code `*.jsonl` transcripts. Each conversation becomes `chat://<origin>/<id>`. |
| Write-back tools | `lake_server/write_tools.py` → `save_document_json()`, `save_conversation_json()`; MCP tools `save_document`, `save_conversation` | Agents send title, content (or messages), optional tags and project. Stored as `generated` / `chat`, derived, redacted, 500k character cap; tags become `tag:<name>` labels and project a `project` label (both `manual` source, because you asked the agent). Searchable after the next `lake work`. |
| GUI | `review.html` "Held back" section, route `POST /quarantine/{sha}/release` | |

**Checks.** `tests/test_secrets_chats.py` (scanner, redaction, quarantine then release, three importers, write-back tools) and `test_gui.py::test_quarantine_shown_and_released_from_review`.

**Please verify on your machine.** The plan said the export schemas were not checked, and they are still unchecked: the importers follow my understanding of the current Claude.ai / ChatGPT exports and Claude Code session files, tested only against hand-made samples. Run each on a real export; fix field names in `chat.py` if they differ. Also not done: the per-chat summary/decisions/open-questions extraction (needs an LLM step), Codex transcripts, generated-file `original.*` attachments, and a CLI command for the importers (call the adapters through `add()` in `lake_cli` or add `lake import-chats`).

---

## W-028 GUI code browser and chats (Done)

**What.** Browse code repos and read saved chats in the web GUI; plus a `lake chats` import command.

| Piece | Where | Why, in plain words |
|---|---|---|
| Views / queries | `packages/lake_server/src/lake_server/browse_views.py` → `repos()`, `repo_listing()`, `file_view()`, `chats()` | Read-only queries that reuse the code tables and the newest indexed commit per repo (`code_tools.LATEST`). |
| Code pages | `gui.py` → `/code`, `/code/{repo}?path=`, `/code/{repo}/file?path=&symbol=`; templates `code_repos.html`, `code_repo.html`, `code_file.html` | Folder-style navigation, source with line anchors (`#L12`, HTML-escaped so code can never inject markup), an outline of symbols linking to their lines, and "used where?" which lists name-match references with links to the exact line. |
| Chat list | `/chats?origin=&tag=`; `chats.html` | Chats newest first with origin, redaction notice and `#tags`; filter by origin (claude, chatgpt, claude-code, agent-saved) or tag. A chat opens in the normal reader, where labels can be edited. |
| Import command | `lake_cli/main.py` → `lake chats <claude\|chatgpt\|claude-code> <path>` | Closes the gap noted in W-027. |

**Checks.** `tests/test_gui.py::test_code_browser_and_chat_list` (builds a real git repo, indexes it, browses folders, opens a file, follows a reference, lists/filter chats).

**Limits.** No syntax highlighting; no per-commit history view; chats are listed by saved date from the manifest, not by conversation date.

---

## W-029 LightRAG pilot behind the eval gate (Partial: gate built, LightRAG not run)

**What.** The machinery to decide whether any graph-based retrieval deserves to be adopted, plus a cheap graph option that needs no AI model. LightRAG itself was **not** piloted (see `docs/adr/0002-lightrag-pilot-deferred.md`): it needs an LLM for entity extraction, and this environment has none.

| Piece | Where | Why, in plain words |
|---|---|---|
| Gate | `evals/gate.py` → `verdict(baseline, candidate)` | A candidate is adopted only if it improves recall@k or MRR by at least 0.05 while losing at most 0.02 on the other. A tie or a tiny gain is a "no". |
| Comparable runs | `evals/run_eval.py` → `evaluate(embedder, k, retriever)`, CLI `--retriever hybrid\|links` | Any retriever with the signature `retriever(engine, embedder, query, limit=k)` can be scored on the same golden set and written to `evals/runs/`. |
| Link expansion (no LLM) | `packages/lake_retrieval/src/lake_retrieval/graph.py` → `search_with_links()` | Takes the top 3 hits, follows explicit links (out and in) to neighbouring documents, and adds each neighbour's best passage (half the score of the hit that led there; tagged `via: link`). Up to 2 of the result slots are reserved for these, so linked evidence can actually appear. Off unless a caller uses it. |

**Checks.** `tests/test_eval_runner.py`: `test_gate_requires_a_real_improvement`, `test_link_expansion_adds_linked_document`.

**To finish the real pilot** (on your machine, with an LLM key and your documents): wrap LightRAG with the retriever signature, run both retrievers with the real embedder on a golden set built from your documents, and ask `verdict()`. The 8-question fixture set is too small to decide anything.
