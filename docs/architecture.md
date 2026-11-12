# Knowledge Lake: Architecture

2026-11-12

> Diagrams live in the Claude Docs version of this document and are not part of this export.
> Each is marked below by a `Diagram:` line with its caption.

## Decisions and non-goals

The lake is a single-user system built on Postgres and an S3-compatible object store, and each choice below names what would make us revisit it.

| Decision | Why | Revisit when |
| --- | --- | --- |
| Python everywhere | one language across parsers, workers and server | a component proves too slow in Python |
| Postgres for vectors, text and graph edges | one store to back up and restore | measured recall or latency misses the eval targets |
| Object store for immutable packages | derived data can always be rebuilt from it | never; this is the root of trust |
| Jobs table, no broker | `SKIP LOCKED` is enough for one user | job volume outgrows one Postgres |
| Docling first, MinerU on rented GPU for failures | free default, paid escalation only where needed | QA failure rate makes escalation the common path |
| MCP returns evidence, not answers | the agent already writes answers | never |
| Web GUI as server-rendered pages in lake_server | one language, no JS build step, same API as agents | a screen needs rich client state, such as a graph canvas |

Non-goals: multi-tenant access, a photo manager (Immich handles photos), generating answers on the server, a public admin UI, custom parsers or OCR, and Kafka or Kubernetes.

## System map

Four processes and two stores run on one private host; agents reach only the `api` through the edge, and a rented GPU is used for batches.

Diagram: system map · 4 agents, 1 edge, 1 host, 1 burst GPU

`api` and `worker` share no memory; they meet in Postgres and the object store. `ingest` reads sources and writes through the registrar, and the GPU endpoint never touches the stores directly.

## Folder structure

The lake is one Python monorepo (uv workspace) with eight packages, each with a single job. Everything outside `packages/` is data, config or tooling.

```text
lake/
├── pyproject.toml          # uv workspace root, shared lint and type config
├── compose.yaml            # local stack: postgres, minio, api, worker
├── Makefile                # up, down, test, eval, restore-drill
├── docs/
│   ├── architecture.md     # this document, exported
│   └── adr/                # one short file per decision change
├── schemas/                # JSON Schema: manifest, job, tool contracts
├── config/
│   ├── rules.yaml          # classification rules, folder priors
│   ├── sources.yaml        # roots, crawl targets, repos
│   └── lakeignore.default  # default ignore rules
├── packages/
│   ├── lake_core/          # db models, migrations, object store, ids, config
│   ├── lake_ingest/        # source adapters and the registrar
│   ├── lake_parsers/       # Docling, MinerU, LlamaParse behind one interface
│   ├── lake_processors/    # chunk, embed, link, label, group, graph
│   ├── lake_code/          # tree-sitter, SCIP, symbol and reference tables
│   ├── lake_retrieval/     # filters, hybrid search, fusion, rerank, citations
│   ├── lake_server/        # MCP, HTTP API, web GUI, auth, scopes
│   └── lake_cli/           # operator commands: ingest, reindex, explain
├── workers/gpu/            # container image for the burst GPU endpoint
├── deploy/
│   ├── local/              # stage A
│   ├── stage-b/            # private always-on host
│   └── stage-c/            # public MCP edge
├── evals/
│   ├── golden/             # question and expected-evidence pairs
│   ├── fixtures/           # tiny repos, PDFs, a fake disk tree
│   └── runs/               # scored results, one file per run
└── tests/                  # unit and integration tests
```

Three rules keep it small: one package per job in the table below, no package outside `packages/` holds Python that other code imports, and anything generated at runtime (packages, indexes, caches) lives in the object store or Postgres, never in the repo.

| Package | Owns | Never contains |
| --- | --- | --- |
| `lake_core` | schema, migrations, IDs, object-store client, settings | business logic |
| `lake_ingest` | one adapter per source, hashing, dedupe, the registrar | parsing |
| `lake_parsers` | file to markdown package, QA scoring, escalation | job scheduling |
| `lake_processors` | the job loop and every derived-data processor | HTTP handling |
| `lake_code` | symbols, references, repo map, dependency-to-docs bridge | generic document logic |
| `lake_retrieval` | query planning, fusion, rerank, citation building | writes to the lake |
| `lake_server` | MCP tools, web GUI routes and templates, auth, rate limits, response shaping | search logic |
| `lake_cli` | operator entry points | anything the server also needs |

## Dependency rules

A package may import only from a lower layer, and a lint check in CI fails the build on any upward or sideways import.

Diagram: dependency layers · 8 packages, 4 layers

1. `lake_server`, `lake_cli`
2. `lake_processors`, `lake_retrieval`
3. `lake_ingest`, `lake_parsers`, `lake_code`
4. `lake_core`

`lake_processors` calls `lake_parsers` for its parse step and `lake_code` for its code-index step. `lake_server` only enqueues jobs and reads results; it never runs a processor itself. Types shared by two packages in the same layer move down into `lake_core`.

## Runtime layout

State lives in three places: the object store for immutable bytes, Postgres for everything derived, and the git repo for config. Nothing else is authoritative.

```text
object store (S3-compatible)
├── originals/<sha256[:2]>/<sha256>        # raw bytes, one per content hash
├── packages/<sha256>/<rev>/               # manifest.json, content.md, structure.json,
│                                          #   assets/, captions.json, original.*
├── derived/<processor>/<version>/...      # bulky processor output (graphs, caches)
└── quarantine/<sha256>                    # denied or secret-flagged files, never indexed

host data dirs
/srv/lake/
├── pg/          # postgres data
├── minio/       # object store data, when self-hosted
├── cache/       # model weights, parser caches; safe to delete
└── backups/     # nightly dumps and object-store snapshots
```

Packages are immutable: a re-parse writes a new `<rev>`, and one revision is marked canonical in Postgres. Everything in `derived/` and every Postgres table except `source`, `location` and the canonical-revision pointer can be rebuilt from `packages/`, which is what the restore drill proves.

Config is plain files in `config/`, committed to git, with no secrets in it. Secrets arrive as environment variables from the host; `lake_core` is the only package that reads them.

## Data model

One identical file stored in many places is one content row with many locations, so it is parsed, embedded and labelled once.

Diagram: data model · 12 entities, content as hub

The top row is the spine from where a file lives to the vectors made from it: Source, Location, Content, Package, Chunk, with Job under Package and Embedding under Chunk. The bottom row holds satellites: labels, groups, graph edges, code symbols and chat records. They attach to the content hash, so each can be dropped and rebuilt without touching the spine.

## Identity, manifest and citations

Every ID is derived from content or from another ID, so the same input always lands on the same row and a rebuild reproduces them.

| ID | Built from | Changes when |
| --- | --- | --- |
| `content_sha256` | sha256 of the original bytes | never; same bytes, same ID |
| `location_id` | source + path | the file at that path changes hash (new row) |
| `package_id` | `content_sha256` + `rev` | a re-parse writes the next `rev`; one `rev` is canonical |
| `chunk_id` | `package_id` + ordinal + chunker version | the chunker version changes |
| `job_id` | processor + version + target | never; a retry reuses the row |

The manifest is the one file a consumer needs to trust a package. It is validated against `schemas/manifest.schema.json` before the package is published.

```json
{
  "content_sha256": "9f2c…",
  "rev": 2,
  "source_type": "pdf",
  "title": "Designing Data-Intensive Applications",
  "parser": { "name": "docling", "version": "x.y.z" },
  "files": ["content.md", "structure.json", "captions.json", "original.pdf"],
  "assets": 42,
  "qa": { "pages_failed": [], "escalated_to": null },
  "created_at": "2026-11-12T09:00:00Z"
}
```

A citation is a stable address into a package. Evidence returned to agents carries it in both forms:

```text
lake://<content_sha256>#<rev>/<section-or-page>
```

```json
{
  "uri": "lake://9f2c…#2/ch3-replication",
  "title": "Designing Data-Intensive Applications",
  "section": "Chapter 3, Replication",
  "location": "/home/me/books/ddia.pdf",
  "tier": "original"
}
```

`tier` is `original` for ingested sources and `derived` for chats and generated documents, so an agent can weigh them differently.

## Processing core

New data never calls a processor directly. It writes an event, the event creates job rows, and a worker claims one row at a time from Postgres.

Diagram: job loop · claim, run, write, emit, with GPU and retry branches

Workers claim with `FOR UPDATE SKIP LOCKED`, so adding a second worker needs no coordination. A failed job goes back with a later `run_after` and, after its attempt limit, is parked as dead-lettered for a human to look at. There is no Kafka, Celery or Temporal; the jobs table is the queue.

## Processor contract

A processor is a small class that reads one target (a content hash or package id) and writes rows keyed by `(content_sha256, rev, processor, processor_version)`. Bumping `version` makes the job loop reprocess everything it applies to; running twice with the same version changes nothing.

```python
class Processor(Protocol):
    name: str  # "chunk", "embed", "link", "label", ...
    version: str  # bump to trigger reprocessing
    accepts: set[str]  # source types it applies to
    cost: Literal["cpu", "gpu", "llm"]

    def run(self, target: str, ctx: Context) -> None: ...  # ADR 0001
```

| Job field | Meaning |
| --- | --- |
| `id` | derived from processor + version + target |
| `processor`, `version` | which code, which revision of it |
| `target` | the package the job reads |
| `status` | pending, running, done, failed, dead |
| `attempts` | count so far, compared with the limit |
| `run_after` | earliest time a worker may claim it |
| `lease_until` | a crashed worker's claim expires here |
| `error` | last failure message |

Processors that need a GPU declare `cost: gpu`; the worker sends those to the burst endpoint and writes the result itself, so GPU workers hold no database credentials.

## Ingestion

Every source type has its own adapter, but all of them end at the same registrar, so dedupe, package layout and job creation exist once.

Diagram: ingestion lanes · 5 lanes, 1 registrar

A lane only decides how bytes arrive and which lane-specific step runs; it never writes to Postgres or the object store directly.

## Adapter interface

Adapters are the only code that knows about a source. They yield items; the registrar does everything else.

```python
class Adapter(Protocol):
    name: str  # "upload", "crawl", "git", "chat", "disk"

    def scan(self, source: Source) -> Iterator[Item]: ...

    # Item = bytes or a stream + location (path or URL) + mtime + hints
```

| Step | Owner |
| --- | --- |
| Find items, apply ignore rules | adapter |
| Hash, dedupe, write the original and package | registrar |
| Record the location row | registrar |
| Create jobs for the item's type | registrar |

The disk lane adds no processors of its own. It walks read-only, skips ignored subtrees, then yields each file like an upload, so documents reuse the document steps and repos reuse the code steps. Classification and grouping run afterwards as ordinary processors on the content hash.

## Retrieval

A query is filtered first, searched two ways in parallel, fused, reranked and trimmed to a token budget, with graph expansion only when the tool asks for it.

Diagram: retrieval pipeline · 8 steps, 1 optional

Filters run before search, so scope, trust tier and source type cut the candidate set instead of removing results afterwards.

## MCP tools and scopes

The server speaks remote Streamable HTTP. Stages B and C check bearer tokens and scopes; full OAuth (needed by claude.ai and ChatGPT web) is deferred, see ADR 0003. Each tool needs one scope, and every read tool returns evidence with citations.

| Tool | Does | Scope |
| --- | --- | --- |
| `search` | hybrid search over documents, returns ranked passages | `read` |
| `fetch` | full text of one result by its citation URI | `read` |
| `query` | filtered search: source type, label, group, date | `read` |
| `get_document` | manifest, outline and metadata for one package | `read` |
| `neighbors` | linked or similar documents for one package | `read` |
| `resolve_source` | all locations where a content hash lives | `read` |
| `research` | topic in, evidence set and link graph out | `read` |
| `code_search`, `code_find_symbol`, `code_find_references` | search code, find definitions and callers | `code:read` |
| `code_file_outline`, `code_get_file`, `code_repo_map`, `code_dependency_docs` | read structure, files, repo map, linked docs | `code:read` |
| `save_document`, `save_conversation` | write generated documents and chats back | `write` |
| `explain_path` | why a path was indexed, ignored or labelled | `admin` |

Photo results need `photos:read`, are left out of default search, and have GPS stripped before they reach a cloud agent.

`search` and `fetch` use exactly those names and one string argument each, because ChatGPT's connector only accepts that shape. The other tools carry richer arguments for Claude and Codex.

Every result is a list of passages, each with the citation object from the identity section, a score and the `tier` flag. A response never contains a generated answer.

## Web GUI

The GUI is a set of server-rendered pages inside `lake_server` (FastAPI, Jinja templates, HTMX). It calls `lake_retrieval` and `lake_core` the same way an MCP tool does, so you and your agents see the same data, with no second backend and no JS build step.

| Screen | You can | Writes | Scope |
| --- | --- | --- | --- |
| Browse and search | walk the tree by source, folder, label or group; run the same search agents use | nothing | `read` |
| Reader | read a package's markdown with page images, outline, links in and out, and versions; open the original or edit its markdown | notes | `read`, `write` |
| Code | browse repos, file outlines, symbols and references | nothing | `code:read` |
| Chats | read saved conversations by date and source | tags | `read`, `write` |
| Review queue | resolve duplicates, version families, topic-cluster suggestions, QA failures and quarantined files | labels, group edits, release decisions | `write` |
| Sources and jobs | add a source, crawl URL or repo; see the queue and failures; retry or reparse | source rows, job actions | `write`, `admin` |

PDFs, images, audio and video open from the original in the browser's own viewers. Photos stay in Immich and are linked from the lake, behind `photos:read`.

**Edits never change a package.** A label, group, note or review decision is an ordinary row marked as made by you, and manual decisions already outrank rules and content signals. Corrected text is saved as a new package revision with `tier: derived`, so the original stays recoverable. The editor is a plain markdown pane beside a server-rendered live preview, with no editor library at first. Saving writes the new revision through the registrar and queues re-chunking and re-embedding for that package only. The same editor creates new notes and documents. Classification and ignore rules stay in `config/`; the GUI shows them read-only next to `explain_path`, and you edit them in git.

**Access.** Pages are served only in stages A and B. In stage C the edge still forwards the MCP path alone. Login is a single-user session behind the VPN or LAN, and every edit needs the same `write` or `admin` scope an agent would need.

## Deployment

The lake starts on one machine and moves outward in three stages; each stage changes network exposure, not code.

Diagram: deployment stages · local, private, public

Promotion means pointing the same `compose.yaml` at a different host and config directory. Stage C adds only the tunnel, OAuth and rate limits in front of the MCP path.

## Network, secrets and backups

| Rule | A Local | B Private | C Public |
| --- | --- | --- | --- |
| Who can reach the API | this machine | VPN or LAN | internet, MCP path only |
| Authentication | none | per-user token | OAuth |
| Rate limits | off | off | on |
| Secrets | `.env`, git-ignored | host environment | host environment |
| Backups | manual | nightly, plus the monthly restore drill | same as B |
| Web GUI reachable | localhost | VPN or LAN | not exposed |

Postgres and the object store never listen on a public interface in any stage. The edge forwards one path to the API container and nothing else; the admin tools (`explain_path` and the CLI) are not reachable through it.

Cloud clients call from fixed provider ranges, so the edge can allowlist them. Anthropic publishes `160.79.104.0/21` for claude.ai; ChatGPT and Codex ranges are checked when stage C is set up.

A backup is a Postgres dump plus the object store, and the restore drill rebuilds a scratch lake from `packages/` alone to prove every derived table can be regenerated.

## Cross-cutting rules

Four rules apply in every package. Data tiers decide what a file may ever do; the other three keep operation boring.

| Tier | Examples | Indexed | Reaches cloud agents |
| --- | --- | --- | --- |
| Denied | keys, credentials, secret-flagged files | no, moved to `quarantine/` | never |
| Private personal | photos, personal documents | yes, separate scope | only with `photos:read`, GPS stripped |
| Work | project documents, code | yes | with `read` or `code:read` |
| Public docs | crawled documentation, papers | yes | with `read` |

- **Observability:** structured JSON logs with `content_sha256` and `job_id` on every line, plus job counts by status and processor exposed as Postgres views. No separate metrics stack at first.
- **Configuration:** typed settings loaded once by `lake_core` from `config/` and environment variables; no package reads either directly.
- **Errors:** processors raise and let the job loop record the failure; retries are the loop's job, not the processor's. A parser that fails QA escalates instead of retrying.

## Test architecture

What a check can break decides when it runs: red means a blocked merge or release for the fast ones, an issue for the scheduled ones.

Diagram: test architecture · 4 triggers, 8 checks

| Trigger | Checks | Red means |
| --- | --- | --- |
| Every commit | unit tests, import-rule lint | blocks merge |
| Every PR | fixture parses, stack integration | blocks release |
| Nightly | retrieval evals, client contracts | opens an issue |
| Monthly | restore drill, licence check | opens an issue |

Fixtures in `evals/fixtures/` (tiny repos, a few PDFs, a fake disk tree with a venv and a `.gitignore`) feed the PR and nightly checks. The golden question set in `evals/golden/` is what retrieval and the graph pilot are measured against.

## Extension points and open questions

Growth is meant to be additive: each of these is one new file plus a registration line, with no change to existing packages.

| To add | Write | Where |
| --- | --- | --- |
| a source type | an `Adapter` | `lake_ingest` |
| a derived index | a `Processor` | `lake_processors` |
| a parser | a parser backend | `lake_parsers` |
| an MCP tool | a schema, then the tool | `schemas/`, `lake_server` |
| another vector or graph store | an index implementation behind the retrieval interface | `lake_retrieval` |
| a GUI screen | a route and a template | `lake_server` |

Open questions, each with what settles it:

- [ ] MinerU licence: its licence changed at 3.1.0, but a third-party weight packaging still lists AGPL-3.0. Read the licence files before using it in the escalation lane.
- [ ] Marker licence: not yet checked.
- [ ] GPU provider: RunPod and Modal prices are vendor-reported; Hugging Face pricing was not verified. Settled by a one-day trial batch.
- [ ] ChatGPT and Codex egress ranges for the stage C allowlist.
- [ ] Photo embeddings (SigLIP or DINOv2): only if Immich search proves too weak.
- [ ] Graph pilot (LightRAG): proceeds only if it beats plain hybrid search on the golden set.
- [ ] Stage B host: which always-on machine, and how it is reached privately.
- [ ] GUI and rules: v1 shows classification and ignore rules read-only. Decide whether the GUI should also write them back to git.
- [ ] Audio and video: the GUI plays originals as they are; transcription is not planned. Confirm that is enough.
