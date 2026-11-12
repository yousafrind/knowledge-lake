# Knowledge Lake

Self-hosted store for documents, code, chats and disk dumps, served to AI agents over MCP.
Specs live in the Claude Docs "Knowledge Lake: Architecture" and "Build Order and Work Items";
`docs/work/` holds the canonical work-item table and one card per item.

## Commands

- `make test` runs ruff, mypy, the import-layer lint and pytest.
- `make lint` runs the first three only.
- One package's tests: `uv run pytest tests/<file>.py`.

## Layer rules

Imports run down four layers; `lint-imports` enforces them (config in `pyproject.toml`).

1. `lake_server`, `lake_cli`
2. `lake_processors`, `lake_retrieval`
3. `lake_ingest`, `lake_parsers`, `lake_code`
4. `lake_core`

No upward imports and no sideways imports within a layer. Shared types move down into `lake_core`.

## Picking up an item

1. Read `docs/work/W-NNN.md` and the sections named in `implements` in `docs/work/items.csv`.
2. Write the failing checks first, then build only what the card lists.
3. Done means: the card's checks pass, `make test` is clean, nothing outside `touches` changed,
   `status` is updated in `items.csv`, and `docs/build-register.md` has an entry for the item.

## Git workflow

No feature branches or PRs. Commit straight to `main` and push, one commit per work item
(or smaller), message starting with the item id, e.g. `W-002: local stack`.
Doc syncs use `docs: sync <name> (rev N)`.

## Build register

`docs/build-register.md` records what each finished item built: where it is (file, class,
function) and why, in plain words. Update it in the same commit as the work.

## Deviations

If the architecture has to change, add a short ADR in `docs/adr/` and update the architecture doc.
Never drift silently.
