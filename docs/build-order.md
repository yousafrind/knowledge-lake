# Knowledge Lake: Build Order and Work Items

> Exported from Claude Docs. The canonical, machine-readable tracker is [`work/items.csv`](work/items.csv);
> each item has a card in `work/W-NNN.md`. Cards exist for W-001 to W-008; for later items the build register (`build-register.md`) is the record.

## How this works

- Items are small, ordered by `needs`. Each has a card: Build, Done when, Not now.
- `implements` points at architecture sections (`arch:<slug>`) and plan requirements (`plan:req-N`), so a dependency graph or architecture map can be generated from the CSV by script.
- Update `status` in `items.csv` in the same commit that finishes the item.

## Walking skeleton

W-001 to W-013 give an end-to-end path: add a file, parse, chunk, embed, search, and fetch it over MCP. Everything after widens it.

## Work items

| ID | Title | Phase | Needs | Touches | Days | Status |
|---|---|---|---|---|---|---|
| W-001 | Repo, tooling and import-rule lint | P0 |  | root, tests | 1 | Done |
| W-002 | Local stack: Postgres with pgvector, object store | P0 | W-001 | deploy/local | 1 | Done |
| W-003 | lake_core: settings, db session, migrations | P0 | W-001, W-002 | lake_core | 1 | Done |
| W-004 | lake_core: schema v1 | P0 | W-003 | lake_core, schemas | 2 | Done |
| W-005 | lake_core: object store and package IO | P0 | W-002, W-003 | lake_core, schemas | 2 | Done |
| W-006 | Registrar | P0 | W-004, W-005 | lake_ingest | 2 | Done |
| W-007 | Job loop and processor contract | P0 | W-004 | lake_processors | 2 | Done |
| W-008 | Upload adapter and lake add | P0 | W-006 | lake_ingest, lake_cli | 1 | Done |
| W-009 | Docling parse processor | P1 | W-006, W-007 | lake_parsers, lake_processors | 2 | Partial |
| W-010 | Chunk processor | P1 | W-009 | lake_processors | 2 | Done |
| W-011 | Embedding and full-text index | P1 | W-010 | lake_processors | 3 | Done |
| W-012 | Hybrid search, fusion and citations | P1 | W-004, W-011 | lake_retrieval | 3 | Done |
| W-013 | MCP server: search and fetch | P1 | W-012 | lake_server | 2 | Done |
| W-014 | Golden question set and eval runner | P1 | W-013 | evals | 2 | Done |
| W-015 | GUI v1: browse, search, reader | P1 | W-013 | lake_server | 4 | Done |
| W-016 | Website crawler adapter | P2 | W-006 | lake_ingest | 4 | Done |
| W-017 | Deterministic link graph | P2 | W-010 | lake_processors | 2 | Done |
| W-018 | QA scoring and MinerU escalation | P2 | W-009 | lake_parsers, workers/gpu | 4 | Done |
| W-019 | Remaining read tools | P2 | W-013, W-017 | lake_server | 2 | Done |
| W-020 | Disk walker and ignore rules | P2b | W-006 | lake_ingest | 3 | Done |
| W-021 | Dedupe, type detection, classify and group | P2b | W-007, W-020 | lake_processors | 5 | Done |
| W-022 | explain_path tool | P2b | W-020 | lake_server, lake_cli | 1 | Done |
| W-023 | GUI review queue, sources, jobs and markdown editor | P2b | W-015, W-021 | lake_server | 5 | Done |
| W-024 | Code adapter and symbols | P3 | W-006, W-007 | lake_code, lake_ingest | 4 | Done |
| W-025 | SCIP references, repo map and code tools | P3 | W-013, W-024 | lake_code, lake_server | 4 | Done |
| W-026 | Docs bridge | P3 | W-016, W-025 | lake_code | 2 | Done |
| W-027 | Chat importers, write-back tools and secret scan | P3 | W-006, W-013 | lake_ingest, lake_server | 4 | Done |
| W-028 | GUI code browser and chats | P3 | W-015, W-025, W-027 | lake_server | 3 | Done |
| W-029 | LightRAG pilot behind the eval gate | P4 | W-014, W-017 | lake_processors | 5 | Partial |
| W-030 | Knowledge broker: research tool | P4 | W-017, W-019 | lake_retrieval, lake_server | 4 | Done |
| W-031 | Stage B: private host, backups, restore drill | P5 | W-002 | deploy/stage-b | 3 | Partial |
| W-032 | Stage C: edge, OAuth, rate limits | P5 | W-013, W-031 | deploy/stage-c, lake_server | 3 | Partial |
| W-033 | Client contract tests | P5 | W-032 | tests | 3 | Done |
| W-034 | Observability views and licence check | P5 | W-007 | lake_core, lake_processors | 2 | Done |

## Open questions

- The architecture says the registrar writes the package, but for binary files the parse processor does. Flagged in the W-006 card; settle before W-009.
