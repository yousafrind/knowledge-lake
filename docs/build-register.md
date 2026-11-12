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
