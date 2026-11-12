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
