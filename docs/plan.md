# Knowledge Lake: Plan

Nov 12, 2026 · @yousaf M Rind

## Summary and assumptions

Build the lake around one Postgres database plus an object store, a parser tier that turns every source into a self-contained markdown package, a set of pluggable processors that read those packages, and one MCP server that every agent (Claude, Codex, ChatGPT) talks to. Start with Postgres doing vectors, full-text and the graph; add Qdrant or Neo4j only when a measured problem demands it.

**Where I'm pushing back (simplicity first).** Your list implies six or more datastores on day one (vector DB, graph DB, search index, queue, object store, code index). That is the usual way these projects stall. Everything in requirements 0 to 5 fits on Postgres (pgvector, tsvector, relational graph tables) and S3-compatible storage. Each processor writes derived data keyed by a document ID, so any index can be dropped and rebuilt from the markdown packages.

**Assumptions I'm making (correct any of these):**

- One user, a few agents, no multi-tenant needs.
- Content is private and includes copyrighted books and papers, so the lake is never public and never shared.
- Backend in Python (the parsing and RAG ecosystem is Python-first); the MCP server and web UI can be TypeScript or Python.
- No local GPU. GPU is rented in bursts for parsing and embeddings.
- Low monthly budget; the open questions at the end ask for a number.
- Time estimates in the roadmap assume one developer working part-time. They are my estimates, not sourced.

This document is the plan only. No code has been written.

## Architecture at a glance

&#91;embedded content: architecture · 7 tiers, 1 write-back loop\]

Writes flow down from sources to Postgres; agents read back up through the MCP server. The loop on the right is the save-to-lake path that feeds chats and generated documents back in as new packages.

## Req 0: crawler, ingestion and the MCP server

Use [Crawl4AI](https://www.scrapingbee.com/blog/crawl4ai/) as the default crawler: it is a self-hosted library, [Apache 2.0](https://scrappey.com/qa/web-scraping-apis/crawl4ai-vs-firecrawl), with deep-crawl support. Firecrawl is the fallback: its core is [AGPL-3.0 and self-hostable](https://toolhalla.ai/blog/firecrawl-vs-crawl4ai-vs-jina-reader-2026), but its self-hosted version is a [multi-service docker-compose setup](https://fastcrw.com/blog/firecrawl-vs-crawl4ai-vs-crw). One vendor [benchmark of 1,000 URLs](https://spider.cloud/blog/firecrawl-vs-crawl4ai-vs-spider-honest-benchmark/) had Firecrawl ahead on success rate (95.3% vs 89.7%), mostly on bot-protected pages. Documentation sites rarely need that, and the benchmark's author sells a competing crawler, so treat it as a hint.

**Crawl pipeline, in order:**

1. **Source registry.** A table of seeds with scope rules (domain, path prefix, depth, page cap), library name and version, and a refresh interval.
2. **Discovery.** Prefer a docs GitHub repo (clone the markdown directly, no scraping), then `llms.txt` / `llms-full.txt` if the site publishes one, then `sitemap.xml`, then link following. Always honour robots.txt and rate-limit per host.
3. **Fetch and render.** Crawl4AI with Playwright only for JavaScript-rendered sites; plain HTTP otherwise.
4. **Clean.** Main content only, code fences kept intact, canonical URL and heading anchors preserved.
5. **Change detection.** Content hash per page; unchanged pages are skipped on re-crawl, changed pages create a new document version.
6. **Emit a markdown package** (same format as parsed files, see Req 2).

**Other ways in:** a watched folder, a `lake add <file-or-url>` CLI, and a small upload page. A browser clipper and email-in are later additions.

**MCP server.** One remote server over Streamable HTTP with OAuth, so Claude, ChatGPT and Codex can all use it (details in Req 3). The Context7 pattern is the model: one tool resolves a name to a source (`resolve_source`), another returns ranked, token-budgeted passages (`query`). Context7 already serves public library docs, so the lake should not re-crawl what it serves well; it holds your private docs, pinned versions and everything Context7 lacks.

## Req 1: converting everything to markdown

Default to Docling, escalate hard documents to MinerU on a rented GPU, and keep LlamaParse as an optional paid fallback. LlamaParse's self-hosted edition is Enterprise-only, so it does not meet your free self-hosted requirement. Before locking this in, run all candidates on about 30 of your own documents; every comparison I found says the same.

| Tool | License | Best at | Hardware | Self-host |
| --- | --- | --- | --- | --- |
| [Docling](https://idp-software.com/vendors/docling/) (IBM) | MIT; Granite-Docling model Apache 2.0 | Heading hierarchy, many formats (PDF, DOCX, PPTX, XLSX), light deploy | CPU works; GPU optional | Yes: [docling-serve](https://pypi.org/project/docling-serve/1.19.0/) with CPU and CUDA images |
| [MinerU](https://www.opensourcealternatives.to/item/mineru) | Moved from AGPLv3 to an Apache-2.0-based license with attribution and commercial thresholds from [3.1.0](https://toolnavs.com/article/2457-is-mineru-worth-using-the-50k-star-pdf-to-markdown-tool-has-deployment-and-licen) | Scientific papers, formulas to LaTeX, CJK, header/footer removal | VLM backend needs [NVIDIA GPU, 8 GB+ VRAM](https://hub.docker.com/r/windoze/mineru); pipeline backend runs on CPU | Yes: REST API, Gradio, OpenAI-compatible VLM server |
| [Marker](https://particula.tech/blog/docling-vs-mineru-vs-marker-pdf-parser) | Check before use; the source calls license the first deciding factor | Clean markdown, good headings | GPU preferred | Yes |
| [LlamaParse](https://developers.llamaindex.ai/python/cloud/self_hosting/) | Hosted service | Hard tables, merged cells, cross-page tables | None (cloud) | Enterprise plans only |
| [PyMuPDF4LLM](https://gitcode.csdn.net/69f1a0b10a2f6a37c5a6c44d.html) | Not checked | Fastest, zero dependencies | CPU | Library |

**LlamaParse in numbers.** Credits cost [$1.25 per 1,000](https://markaicode.com/pricing/llamaparse-pricing/). Tiers are Fast (1 credit per page), Cost Effective (3), Agentic (10) and Agentic Plus (45). The free plan includes [10,000 credits a month](https://www.modern-datatools.com/tools/llamaindex/pricing). A 10,000-page book collection at Cost Effective is 30,000 credits, about $37.50 (my arithmetic). Its open-source sibling, LiteParse, is positioned as the [local option](https://gmagazine.it.com/?p=566), with LlamaParse as the paid path for hard documents.

**License caution on MinerU.** The project says it dropped AGPL, but a third-party packaging of the MinerU2.5 weights on Hugging Face still [lists them as AGPL-3.0](https://huggingface.co/raoqu/mlx-mu). For private personal use this does not matter. If you ever expose the lake as a service, read the current license text first.

**Routing rule.** Parse with Docling first. Re-parse with MinerU when a page fails a quality check: very low text density on a text-bearing page, formulas detected, or tables flagged. Store both outputs and mark which one is canonical. Always keep the original file.

**Where to run the GPU.**

- **Burst, not 24/7.** Parsing is batchy, so rent per second or per hour. The break-even rule from [gpuperhour](https://gpuperhour.com/blog/serverless-gpu-pricing): serverless is cheaper while the GPU is busy less than (dedicated hourly price ÷ serverless per-hour equivalent) of the time.
- **RunPod.** Serverless flex workers scale to zero and bill per second; the 24 GB class (L4, A5000, 3090) is [about $0.69/hr equivalent and L40S about $1.75/hr](https://lyceum.technology/magazine/modal-vs-runpod-for-serverless-gpu-inference/). A community-cloud RTX 4090 is [about $0.34/hr](https://dupple.com/tools/runpod). One author reports [about $0.001 per page warm](https://dev.to/sergeyshmakov/how-to-self-host-the-mineru-api-on-runpod-2ejp) for MinerU on a 24 GB 4090. That author sells a MinerU hosting service, so verify with your own batch.
- **Modal.** Per-second billing and [$30 a month in free credits](https://vibereference.vercel.app/cloud-and-hosting/ml-inference-gpu-platforms); L4 is about [$0.80/hr](https://www.runpod.io/articles/comparison/runpod-vs-modal) (Modal's rate as quoted by a RunPod page).
- **Hugging Face (GPU Spaces or Inference Endpoints).** I did not verify HF pricing, so it is not compared here. It is a reasonable place to host the Granite-Docling model or embedding models if you already have an account.

At roughly a tenth of a cent per page, a 5,000-page backlog costs single-digit dollars. The cost to manage is cold starts and operations, not compute, so pick whichever provider you will actually keep configured.

## Req 2: the markdown package and the processing modules

Every source, whether a PDF, a crawled page, a chat or a repo README, becomes one immutable **package** in object storage. Processors only read packages and only write derived rows keyed by `(doc_id, version, processor, processor_version)`. That one rule lets you add, replace or rebuild any module without re-parsing anything.

```
<doc_id>/<version>/
  manifest.json    id, type, source URL or path, content hash, parser + version,
                   library + version, tags, trust tier, created_at
  content.md       canonical markdown, images referenced by relative path
  structure.json   block list with page, bbox and type (Docling JSON or MinerU content list)
  assets/          images, figures, tables as CSV
  captions.json    VLM descriptions of figures (added later by a processor)
  original.*       the source file, untouched
```

Docling exports markdown plus a structured document, and [MinerU writes markdown, images and structured output](https://recca0120.github.io/en/2026/04/24/mineru-pdf-to-markdown/) side by side, so `structure.json` comes free from both.

**Job model.** A `package.created` event enqueues one job per enabled processor. Use a Postgres jobs table (`FOR UPDATE SKIP LOCKED`), not Kafka, Celery or Temporal. Jobs are idempotent and carry a processor version, so bumping a version re-runs just that module.

**Modules, with the order to build them:**

| # | Module | Output | Notes |
| --- | --- | --- | --- |
| 1 | Registrar | manifest row, dedupe by hash | First; everything depends on it |
| 2 | Chunker | chunks with heading path, page, parent section | Structure-aware: split on headings, keep tables and code blocks whole, small chunks match while the parent section is returned for context |
| 3 | Embedder | dense and sparse vectors | [BGE-M3](https://wz-it.com/en/knowledge/ki/hybrid-search-reranking/) gives dense (1,024 dims), sparse and multi-vector output from one model |
| 4 | Index builder | pgvector HNSW, tsvector, document catalog | Hybrid retrieval fused with reciprocal rank fusion; also writes per-collection indexes and an `llms.txt`-style table of contents |
| 5 | Link graph | doc to section to chunk edges, hyperlinks, citations, dependency edges | Deterministic and cheap; covers most of the broker's needs |
| 6 | Entity graph | entities and relations from an LLM | [LightRAG](https://www.beri.net/learning/lightrag-graph-rag-docs) builds a graph plus vectors, adds documents incrementally and can store in Postgres or Neo4j. Microsoft's GraphRAG [cost about $33K to index a large corpus in 2024](https://callsphere.ai/blog/vw6g-microsoft-graphrag-knowledge-graph-2026), so run entity extraction per collection, not on everything |
| 7 | Knowledge broker | topic dossier: subgraph, ranked reading list, gaps | Given a topic: retrieve seeds, expand through graph edges, pull related documents into one markdown dossier saved back into the lake as a derived document |

**Suggested additions** (the list should grow; these are in rough value order):

- **Document cards.** Multi-level summaries (document, section) written once; they make catalogs and broker output readable.
- **Parse QA scorer.** Per-page quality score that drives the Docling to MinerU escalation.
- **Near-duplicate and version detector.** MinHash on chunks; links v1 and v2 of a paper or book edition.
- **Citation resolver.** Parses bibliographies and links references to other documents in the lake, which gives the broker real edges.
- **Figure and table processor.** VLM captions for images; tables exported as CSV.
- **Glossary and entity canonicalizer.** Merges "LLM", "large language model" and project-specific aliases.
- **Auto-collections.** Clusters embeddings and proposes tags and collections for review.
- **Freshness tracker.** Marks crawled docs stale and re-queues them; flags when a library version is superseded.
- **Eval harness.** Golden question set run after every change; treated as a module because retrieval regressions are otherwise silent.
- **Weekly digest.** What was added, what changed, what the broker would read next.

**Pushback on the graph.** The entity graph is the costliest and least certain module: [extraction quality depends on the LLM, and open models may need 30B+ parameters](https://dev.co/ai/frameworks/lightrag), and a graph [needs ongoing maintenance or it rots](https://tianpan.co/blog/2026-04-09-graphrag-production-when-vector-search-hits-ceiling). Build module 5 first, then pilot module 6 on one collection and keep it only if the eval harness shows it beating hybrid search plus link expansion.

## Req 3: retrieval and agent integration

The MCP server returns evidence, not answers: ranked passages with citations that the calling agent synthesizes. That keeps the read path fast, cheap and independent of any LLM key on the server.

**Retrieval pipeline:** optional query rewrite (done by the calling agent) → hybrid retrieval (dense, sparse and full-text, fused with reciprocal rank fusion) → metadata filters (collection, library, version, type, date) → cross-encoder rerank → optional graph expansion to neighbours → assemble to a token budget with citations (document, version, page or section, source URL). A [two-stage hybrid plus rerank design](https://wz-it.com/en/knowledge/ki/hybrid-search-reranking/) is the standard pattern, and [pure vector search misses exact strings such as part numbers or error codes](https://techsy.io/de/blog/hybrid-search-bm25-vs-vector).

**Tool surface (keep it small, about ten tools):**

| Tool | Purpose |
| --- | --- |
| `search`, `fetch` | Exactly these names and shapes, for ChatGPT's connector contract (see below) |
| `query` | Richer search: filters, token budget, rerank on or off |
| `get_document` | Markdown slices by section or page range |
| `neighbors` | Graph expansion from a document or chunk |
| `resolve_source` | Library or collection name to ID, Context7-style |
| `research` | Starts a broker dossier job; returns a job ID and later a document |
| `code_*` | Code tools from Req 5 |
| `save_document`, `save_conversation` | Write path from Req 4 |

**Connecting each client:**

| Client | How | Catch |
| --- | --- | --- |
| Claude (web, desktop, mobile) | [Custom connector](https://support.anthropic.com/en/articles/11503834-building-custom-connectors-via-remote-mcp-servers) to a remote server; Streamable HTTP, OAuth supported | Requests come from [Anthropic's cloud](https://mer.vin/2026/08/local-vs-remote-mcp-claude-custom-connectors/), so the server must be publicly reachable; a VPN-only server is blocked |
| Claude Code | `claude mcp add --transport http <name> <url>`, sign in with `/mcp` | None notable |
| ChatGPT | [Remote servers only; Developer Mode for general tools; user-consented OAuth](https://zuplo.com/learn/mcp/compatibility/clients/chatgpt-connectors) | Early connectors were limited to `search` and `fetch`, hence the two fixed tool names |
| Codex | `codex mcp add <name> --url <url>`, then `codex mcp login`, or an [`http_headers` API key for headless use](https://mcpbundles.com/blog/state-of-mcp-clients) | Fine on a private network |

**Security consequence.** Because claude.ai and ChatGPT call from the cloud, the endpoint must be on the public internet. Put it behind OAuth with a single allowed identity, rate limiting and audit logs, and expose only the MCP path, not the admin UI. If you only use Claude Code and Codex, keep everything on a private network (Tailscale) instead. This choice drives the deployment plan.

**Quality gate.** Build a golden set of 50 to 100 questions from your own documents, each with the expected source passage. Track recall@k, MRR and citation correctness, and run it in CI. Without it, every later change to chunking, embeddings or reranking is guesswork.

## Req 4: saving chats and generated documents

Treat a chat as a source type with its own package: `content.md` holds the turns, `assets/` holds attachments, and the manifest links to any documents the chat produced. Three capture paths, in the order I'd build them:

1. **Write-back tools (the reliable one).** `save_document` and `save_conversation` on the MCP server. You tell the agent "save this to the lake" and it sends the content with title, tags and project. This works the same in Claude, ChatGPT and Codex and needs no scraping.
2. **Export importers.** Claude.ai and ChatGPT both offer account data exports; write one importer per format and run it monthly or on demand. I have not checked the current export schemas, so confirm them when this phase starts.
3. **Local agent transcripts.** Claude Code and Codex keep session transcripts on disk. A session-end hook or a small watcher can push them to the lake. Check the exact paths and file format for each tool at build time.

A browser extension that scrapes chat pages is fragile and I would skip it.

**Design rules:**

- **Trust tier.** Chats and generated documents are model output, not primary sources. Store `trust: derived` in the manifest, and let `search` exclude derived content by default in research mode. Otherwise the lake starts citing its own earlier answers as evidence.
- **Extract, don't just store.** A processor produces a summary, the decisions made and the open questions per chat, and links the chat to the documents it discussed.
- **Secrets scan before storing.** Chats routinely contain API keys and tokens. Run a regex-based secret scanner on ingest and redact or reject.
- **Generated files.** Store the file as a package of its own (type `generated`), linked to the chat. Keep the original format as `original.*` and the markdown rendering as `content.md`.

## Req 5: code base indexer as a first-class source

First-class means a repository is not a pile of text files pushed through the document pipeline. It has its own parser, chunking, graph, version model and tools. Do not write parsers: wrap tree-sitter and existing SCIP indexers.

**Layers:**

| Layer | Technique | Answers |
| --- | --- | --- |
| Lexical | Postgres full-text plus `pg_trgm` (ripgrep for local repos) | Exact identifiers, config keys, error strings |
| Symbols | tree-sitter definitions with signature, docstring, line range | "Where is X defined?", file outlines |
| Precise references | SCIP indexers where one exists (TypeScript, Python, Rust and others); tree-sitter fallback otherwise | Definitions, references, implementations |
| Semantic | Embeddings of symbol-level chunks with path and docstring context, fused with lexical | "Where do we validate refunds?" |
| Graph | file to symbol, import, call and inheritance edges; commit and ownership edges | Impact analysis, repo map |
| Docs bridge | Parse `package.json`, `pyproject.toml`, `Cargo.toml` and link each dependency to its documentation in the lake | "How do I use the library this code imports?" |

Open-source MCP code indexers already combine [SQLite FTS5, tree-sitter symbols and Qdrant-backed semantic search](https://glama.ai/mcp/servers/a7vulnkovz), and some emit a [SCIP index](https://glama.ai/mcp/servers/v7s1hxpf8j). That confirms the layering works; the lake's differentiator is the docs bridge and cross-repo reach.

**Versioning and updates.** Index per `(repo, commit SHA)` with a content hash per file, so only changed files are re-parsed. Index the default branch continuously and other branches on demand. A git hook or CI step triggers indexing for your own repos; a server-side clone with a deploy token handles GitHub repos. Skip `.env` files and run the secret scanner.

**Tools:** `code_search`, `find_symbol`, `find_references`, `file_outline`, `get_file` (line ranges), `repo_map`, `code_neighbors`, `dependency_docs`.

**Honest caveat.** Claude Code and Codex already grep and read files well inside the repo they are working in. The lake adds value for cross-repo questions ("how did I solve this in another project?"), history, and linking code to the right library docs. Phase 1 should prove that value on two or three of your real repos before investing in SCIP for every language.

## Req 6: whole-disk and backup ingestion

Treat your disk and backups as a second, filesystem-level crawler that **inventories and classifies in place**, and only sends the files worth reading into the parsing pipeline. Do not copy terabytes into the lake, and do not rebuild a photo manager. Groups of similar files are built as rows in the index, so no file is ever moved or renamed.

**Assumptions to confirm:** the disk and each backup set can be mounted read-only; backups kept as Time Machine, restic, borg or disk images must be mounted or extracted first (I have not checked tooling per format); the disk is mostly code and documents, so most files go through the existing document and code lanes, and only the remainder (photos, media, binaries) stays catalog-only.

**Crawler stages, cheapest first:**

1. **Walk and inventory.** One row per file: backup set, path, size, times, inode. A default-deny list is applied here (see safety rules below).
2. **Exact duplicates.** Group by size, then a partial hash, then a full hash, as [Czkawka does](https://www.ghacks.net/?p=170722) (name, size, hash or first-megabyte hash). Hashes are cached so [rescans do not hash the same file twice](https://qarmin.github.io/czkawka/instructions/Instruction.html).
3. **Type detection.** Use [Magika](https://google.github.io/magika) rather than trusting extensions: a [deep-learning model that runs on a single CPU, about 99% F1 over 100+ content types](https://arxiv.org/pdf/2409.13768) (the project now cites [200+](https://notes.billmill.org/computer_usage/image_commands/magika_-_file_type_detection.html)).
4. **Metadata.** EXIF (date, GPS, camera), document properties, audio tags.
5. **Classify** (next section).
6. **Group** (section after).
7. **Route.** Documents to the Docling/MinerU lane; repo roots to the code indexer (Req 5); photos to the media lane; everything else stays catalog-only.

**Reuse of the existing pipeline (the disk is mostly code and documents).** The filesystem crawler is only another source adapter: it emits the same packages and jobs as Reqs 1 to 5 and adds no new processors.

- **One package per content hash.** The same document shows up on the disk and in several backups. Parse it once and record every path as a location row, so each extra backup adds inventory rows but no parsing cost. This is the Registrar's dedupe step from Req 2.
- **Documents.** PDF and Office files go to the Docling lane, with MinerU escalation for pages that fail the quality check (Req 1). Markdown and plain text skip parsing and become packages directly.
- **Code.** A directory containing `.git` is a repo root and goes to the code indexer (Req 5), indexed by commit. A code folder without `.git`, such as a copy inside a backup, is indexed as a snapshot and linked to the repo it matches as a version family.
- **Skip generated and vendored code.** `node_modules`, virtual environments, `target`, `dist`, build output and caches are ignored entirely: never hashed, typed, parsed or embedded (see the ignore rules below). Keep manifests and lockfiles, because the docs bridge reads them.
- **Repos duplicated across backups.** Index the newest copy in full; for older copies index only the files whose content hash differs. This is my design suggestion, to be checked on a few of your repos.
- **Estimate before parsing.** The inventory gives file and page counts by type, so estimate the parse bill first. At roughly $0.001 per page (a vendor-reported figure, see Req 1), 100,000 pages would be about $100 (my arithmetic); confirm on your own batch.
- **More secrets in code.** A code-heavy disk holds more credentials. Scan working trees and git history for secrets before indexing any commit.

**Ignore rules: what is never read.** They run during the walk, so an ignored folder is not descended into, hashed or counted file by file. The markers below are my design choices, not sourced, so test them on your own folders.

1. **Marker-based pruning.** A folder is skipped when it is recognisably generated, whatever its name: a virtualenv (it contains `pyvenv.cfg`), `node_modules`, `__pycache__`, `.tox`, tool caches (folders carrying a `CACHEDIR.TAG` file), and build output next to its manifest (`target` beside `Cargo.toml`, `dist` or `build` beside `package.json` or `pyproject.toml`).
2. **Git's own answer inside repos.** For every repo root the candidate file list is what git reports (`git ls-files --cached --others --exclude-standard`): tracked files plus untracked files that are not ignored. That honours nested `.gitignore` files, the global ignore file and `.git/info/exclude`. Existing code indexers [already use ](https://glama.ai/mcp/servers/@vrppaul/semantic-code-mcp/tree/e02a61c6c6a62c5b6498302c31aea19c46f3188d)[`git ls-files`](https://glama.ai/mcp/servers/@vrppaul/semantic-code-mcp/tree/e02a61c6c6a62c5b6498302c31aea19c46f3188d)[ for file discovery](https://glama.ai/mcp/servers/@vrppaul/semantic-code-mcp/tree/e02a61c6c6a62c5b6498302c31aea19c46f3188d).
3. **Folders without `.git`,** such as copies inside a backup: apply rule 1, plus any `.gitignore` file found in the tree, parsed with gitignore semantics.
4. **Your own `.lakeignore`,** in gitignore syntax, at the disk root or in any folder. It wins over rules 1 to 3, and `!pattern` re-includes something.
5. **Record the skip, not the files.** Store one row per ignored subtree (path, matching rule, file count and size if cheap) instead of a row per file, because one `node_modules` can hold tens of thousands. An `explain_path` tool answers "why wasn't this indexed?", and a report lists the largest ignored subtrees so you can sanity-check.
6. **Ignored is not deleted.** Nothing on disk is touched. Gitignored files are often the sensitive ones (`.env`, local configs), so ignoring them is also the safe default.
7. **Test first.** A fixture repo with a venv, `node_modules`, a gitignored secret file and one tracked source file; the test passes only if just the source file reaches the index.

**Classification: folder tree first, then evidence.** Every directory carries labels that its files inherit (for example `/Backups/2019-phone/DCIM` gives `photos` and `2019`). A rules file you maintain maps path tokens (years, project names, `Taxes`, `Invoices`) to labels. Precedence, highest first: your explicit rules and manual decisions, folder priors, content signals (type, metadata, language), then embedding-cluster suggestions. A child folder overrides its parent only when content signals disagree strongly. Each label is stored as `(file, label, source, confidence)`, and a manual decision is never overwritten by a later run.

**Composition at the index level.** Groups are computed rows `(group_id, kind, members, confidence, rule)`. They feed search filters ("search only within this project"), the broker's topic dossiers, and a review screen where you accept or split groups.

| Group kind | Signal | Example |
| --- | --- | --- |
| Exact duplicates | Content hash | The same file on the disk and in three backups: one canonical record, many locations |
| Near-duplicate images | [Perceptual hash](https://qarmin.github.io/czkawka/instructions/Instruction.html): similar inputs give similar hashes | A resized or edited copy of a photo |
| Version families | Name-stem similarity, text near-duplicates (MinHash), modified times | `report_v1`, `report_final`, `report_final2` |
| Project bundles | A marker (`.git`, `package.json`, `.tex` plus bibliography) or a subtree with high internal similarity | A repo, a thesis folder |
| Photo events | EXIF time gaps, GPS proximity, folder | "Trip, summer 2019" |
| Topic clusters | Clustered document embeddings | Proposed collections for you to name or reject |
| Backup lineages | Same relative path across backup sets | The history of one file over time |

**Reuse, don't rebuild.** Czkawka is a Rust tool with exact-duplicate, [similar-image and similar-video detection and a persistent cache](https://rustutils.com/tools/czkawka/); fclones suits [large-scale automation](https://www.itechguides.com/?p=414231). Wrap them as inventory steps. The lake's own work is the unified catalog, the classification rules, the groups and agent access.

**Photos and media lane.**

- **Start with Immich beside the lake.** It is [self-hosted, AGPL-3.0, with face recognition and semantic search](https://contabo.com/blog/what-is-immich/) from a machine-learning container, which is what you would otherwise build. The lake then holds photo metadata and event groups and links out, instead of duplicating a photo app.
- **If you want photos in the same MCP search,** embed them yourself. [CLIP-style models such as SigLIP put images and text in one vector space, so words can search photos](https://playground.roboflow.com/models/task/image-embedding); [SigLIP is Apache 2.0](https://playground.roboflow.com/models/google/siglip). For duplicate and exact-instance matching, [self-supervised models like DINOv2 fit better, and you should choose before building the index](https://playground.roboflow.com/models/task/image-similarity).
- **Plan for a one-off GPU burst.** A bulk import [runs every image through face detection, face embedding and CLIP embedding](https://dev.to/pickuma/immich-review-self-hosted-google-photos-alternative-for-developers-1279). Immich's baseline is about [4 GB RAM, with 8 GB or more recommended](https://contabo.com/blog/what-is-immich/).
- **Video and audio:** catalog only in the first pass; transcripts can come later.

**Privacy and safety rules for a whole-disk dump** (the main risk in this extension):

- **Default-deny list:** browser profiles and cookies, password-manager vaults, SSH and GPG keys, `.env` and cloud credential files, wallets, system folders, app caches, VM and disk images. Denied files are logged with a reason and never indexed.
- **Secret scan** on every text file; hits are quarantined.
- **Photos stay in their own collection** with a separate `photos:read` scope, excluded from default `search`, and with GPS stripped from anything returned to cloud agents unless you allow it. Anything an agent retrieves is sent to that agent's vendor, so a photo or document surfaced to claude.ai or ChatGPT leaves your machine.
- **Faces of other people:** keep recognition local. Biometric rules vary by place and I am not a lawyer, so check this before sharing the lake with anyone.
- **Read-only sources:** the crawler never writes, moves or deletes on the disk or backups.
- **LLM steps** (captioning, entity extraction) run only on collections you have enabled, never on the whole disk by default.

**Roadmap impact (my proposal).** Add a phase "P2b Disk inventory" after P2: inventory, dedupe, type detection, folder rules and groups, with parsing left to the existing document and code lanes. Gate: the whole disk and every backup set are inventoried, and 30 randomly sampled groups are judged correct by you. The photo lane follows as its own phase after P3. Repos found on the disk are indexed once the code indexer exists in P3. The roadmap diagram is not updated yet.

**Questions that change this section:**

- How large is the disk plus backups (TB and rough file count), and which OS and backup formats?
- For photos, do you want to browse and search by content and faces (Immich is enough), or have agents retrieve them too?
- Should photos and personal documents be reachable from claude.ai and ChatGPT at all, or only from local agents?

## Req 7: browse and edit GUI

Build a private web app where you can browse, read and correct the lake yourself, on the same API the agents use. It is served by the existing API service, so there is no second backend.

**Framework choice.** Server-rendered pages (FastAPI, Jinja templates, HTMX) inside the API. That keeps one language and has no JS build step. A single-page app is not needed until a screen needs rich client state, such as a graph canvas; add one then as a small island.

| Screen | You can | Edits |
| --- | --- | --- |
| Browse and search | walk the tree by source, folder, label or group; run the same hybrid search agents use | none |
| Reader | read a document's markdown with page images, outline, links in and out and versions; open the original or edit its markdown | notes |
| Code | browse repos, file outlines, symbols and references | none |
| Chats | read saved conversations by date and source | tags |
| Review queue | resolve duplicates, version families, topic-cluster suggestions, QA failures and quarantined files | labels, group edits, release decisions |
| Sources and jobs | add a source, crawl URL or repo; see the queue and failures; retry or reparse | source rows, job actions |

**Edit rule.** Edits never change a stored package. A label, group, note or review decision is an ordinary row marked as made by you, and manual decisions already outrank rules and content signals. Corrected text is saved as a new package revision marked derived, so the original stays recoverable. The markdown editor is a plain text pane beside a live preview, with no editor library at first. Saving queues re-chunking and re-embedding for that document only, and the same editor creates new notes and documents. Classification and ignore rules stay in files under git; the GUI shows them read-only with `explain_path`.

**Watching and reading.** PDFs, images, audio and video open from the original in the browser's own viewers. Photos stay in Immich and are linked from the lake behind the `photos:read` scope. Transcribing audio or video is not planned.

**Access.** Private only: it runs in stages A and B, and stage C still exposes the MCP path alone. Single-user login behind the VPN or LAN, and every edit needs the same `write` or `admin` scope an agent would.

**Roadmap.** Browse, search and the reader ship with Phase 1, since they need only the retrieval API. The review queue and sources screens ship with Phase 2b, when disk review work first appears. The code browser ships with Phase 3. My estimate is about a week added to Phase 1 and a week to Phase 2b.

**Questions for you:**

- Should the GUI also write classification and ignore rules back to git, or stay read-only on them?
- Is playing audio and video as-is enough, with no transcripts?

## Data model and tech stack

One Postgres database is the system of record for everything except file bytes. Every choice below has a named trigger for swapping it out, so nothing is added speculatively.

| Layer | Start with | Swap when |
| --- | --- | --- |
| Database | Postgres with `pgvector`, `pg_trgm`, full-text search | [Qdrant](https://www.modern-datatools.com/compare/pgvector-vs-qdrant) when you pass tens of millions of vectors or need native sparse-dense hybrid at low latency |
| Object store | Any S3-compatible bucket (MinIO locally, R2 or S3 hosted) | Never needed; keep it S3-compatible |
| API and workers | Python (FastAPI), Postgres-backed job table | A real queue only if job volume outgrows `SKIP LOCKED` |
| MCP server | Official MCP SDK, Streamable HTTP, OAuth | Cloudflare-style managed hosting if OAuth becomes the time sink (Anthropic's docs [mention it](https://support.anthropic.com/en/articles/11503834-building-custom-connectors-via-remote-mcp-servers)) |
| Crawl and parse | Crawl4AI, docling-serve, mineru-api as containers | Firecrawl for protected sites; LlamaParse free tier for rare hard documents |
| Embeddings and rerank | BGE-M3 plus a cross-encoder reranker | Whatever wins on your golden set; store the model name and version with every vector |
| Graph | Edge table in Postgres with recursive queries; LightRAG with its Postgres backend for the entity layer | Neo4j only if traversal queries get slow or awkward |
| Code | tree-sitter plus SCIP indexers | A hosted code search only if you outgrow this |
| UI | A thin admin page: sources, job status, search playground | Defer until Phase 2 |

**Core tables:** `sources`, `documents`, `versions`, `chunks`, `embeddings`, `edges`, `entities`, `jobs`, `conversations`, `code_repos`, `code_files`, `symbols`, `refs`. Derived tables (`chunks` onward) can be dropped and rebuilt from the packages; `sources`, `documents`, `versions` and `conversations` are the irreplaceable ones and drive the backup plan.

## Development plan

Every phase starts from a verifiable goal and a test written first, so "it works" always means a check passes.

**Repository layout (monorepo):**

- `core/`: schema, migrations (Alembic), package read/write, settings
- `ingest/`: crawler, uploader, watcher, source registry
- `parsers/`: thin adapters to docling-serve and mineru-api, plus the routing and QA logic
- `processors/`: one folder per module; each exposes `name`, `version` and `run(package) -> rows`
- `server/`: HTTP API and the MCP server
- `codeindex/`: repo walker, tree-sitter and SCIP adapters, git hooks
- `evals/`: golden questions, scorers, parser benchmark set
- `deploy/`: compose files, container images, GPU worker image

**Local environment.** One `docker compose up` brings up Postgres, MinIO, docling-serve (CPU image), the API and a worker. GPU work goes to a remote endpoint even in development, so the local box needs no GPU.

**Test layers:**

- Unit: chunker boundaries, routing rules, package round-trip, secret scanner.
- Fixture parses: about 10 small, checked-in PDFs with expected headings and table counts.
- Contract: run the MCP server against MCP Inspector and a scripted client for each of Claude, ChatGPT and Codex. [Client behaviour changes faster than server code](https://nanohub-mcp.readthedocs.io/en/latest/skill/references/connecting-clients.html), so re-verify on a schedule.
- Retrieval evals: the golden set, run on every change to chunking, embedding, fusion or reranking; nightly in CI.
- Integration: spin up the compose stack in CI and ingest a tiny corpus end to end.

**Working agreements:**

- A processor ships only with an eval or fixture that fails when it breaks.
- Each new module sits behind a feature flag until the eval harness shows it helps.
- Parser and embedder versions are recorded on every output, so reruns are targeted.
- Per-processor cost counters (pages, tokens, GPU seconds) are logged from day one.

## Deployment plan

Deploy in three stages and move up only when the previous one hurts. The stage you need depends on one question: do you want claude.ai and ChatGPT (web) to reach the lake, or only Claude Code and Codex?

| Stage | Where it runs | Exposure | Main cost |
| --- | --- | --- | --- |
| A. Local | Docker compose on your laptop or home server | None; CLI agents use localhost | Electricity; GPU burst rentals during backlog ingestion |
| B. Private always-on | One small VPS or a container platform (Postgres, bucket, API, worker) | Tailscale or similar; CLI agents only | The VPS, a few dollars to low tens a month (check current prices) |
| C. Public MCP | Stage B plus a public HTTPS endpoint for the MCP path only | OAuth, rate limits, allowlist | Same, plus time spent on auth |

**Sizing notes.** The [Docling serve images are large (about 8.7 GB for amd64)](https://pypi.org/project/docling-serve/1.19.0/), so give the disk room. A CPU-only MinerU on a container platform is [fine for low-volume, on-demand parsing, while GPU is roughly 15 times faster for batch work](https://railway.com/deploy/mineru). The MinerU docker image needs an [NVIDIA GPU (Volta or newer, 8 GB+ VRAM) and a CUDA 13.0 compatible driver](https://hub.docker.com/r/windoze/mineru) for the VLM backends. Pin image tags.

**GPU worker.** Package MinerU (and the embedder, if self-hosted) as one container image. The ingest worker sends a page batch to a RunPod or Modal endpoint and falls back to CPU Docling if the GPU endpoint is unavailable. Batch ingestion into bursts so cold starts are amortised.

**Security (Stage C).**

- OAuth with a single allowed identity; separate read and write scopes, because `save_*` tools mutate the lake.
- Claude's connector calls come from [Anthropic's egress range 160.79.104.0/21](https://mer.vin/2026/08/local-vs-remote-mcp-claude-custom-connectors/), which you can allowlist at the edge. I found no equivalent published range for ChatGPT.
- Expose only the MCP path. Admin UI and database stay private.
- Rate limits, audit log of every tool call, encryption at rest, secrets in a secret manager.

**Backups.** Back up what cannot be rebuilt: the object store (versioned bucket, replicated to a second provider), plus nightly Postgres dumps of `sources`, `documents`, `versions` and `conversations`. Derived tables are rebuilt from packages. Do a restore drill into a scratch environment before trusting this, then monthly.

**Releases and rollback.** Immutable image tags; forward-only migrations taken after a fresh dump; processor version bumps trigger targeted reprocessing, not full re-ingest. Rollback is redeploying the previous tag.

**Cost guards.** Hard monthly caps on LLM-based jobs (entity extraction, captioning) and GPU spend, enforced in the job runner, in the same spirit as the [spend caps LlamaCloud gives self-hosted users](https://developers.llamaindex.ai/llamaparse/self_hosting/configuration/usage-controls/). Alert at 80% of any cap.

## Roadmap

&#91;embedded content: roadmap · 6 phases, 6 gates\]

Phase 1 is highlighted because it is the first point where Claude, ChatGPT and Codex can use the lake. Phases 3 and 4 can swap if you want the knowledge graph before code indexing; the gates, not the calendar, decide when to move on.

The GUI from Req 7 is not drawn on this roadmap yet: its read-only screens land inside Phase 1, its review screens inside Phase 2b and its code browser inside Phase 3, with no new gates.

## Risks and open questions

The biggest technical risk is MCP authentication, because ChatGPT is the strictest client and the work is fiddly; test it in Phase 1, not Phase 4.

| Risk | Mitigation |
| --- | --- |
| OAuth for remote MCP is hard to get right across clients | Prototype a hello-world connector against all four clients in Phase 1; consider managed hosting |
| Parse quality varies by document | Routing, per-page QA, keep originals, benchmark on your own files first |
| Entity graph costs more than it returns | Pilot on one collection behind the eval gate, with a spend cap |
| Copyright and site terms | Private use only; respect robots.txt and terms; never expose the lake publicly or redistribute. I'm not a lawyer, so check specifics for anything beyond personal use |
| Embedding model lock-in | Store model name and version per vector; keep a re-embed job ready |
| Lake cites its own earlier chat answers | Trust tier on derived content, excluded from research mode by default |
| Secrets end up in chats or repos | Secret scanner on ingest; skip `.env` files |
| Client behaviour changes | Scheduled contract tests per client |
| Licence terms shift (MinerU already did once) | Record licences in a dependency table; re-check on upgrade |
| Scope creep | Phase gates with exit criteria; every module behind a flag |

**Questions that change the plan:**

- What monthly budget are you comfortable with, and is an always-on host acceptable?
- Roughly how big is the corpus: number of documents and pages, number of repos? This decides pgvector versus Qdrant.
- Must claude.ai and ChatGPT web reach the lake, or are Claude Code and Codex enough at first? This decides Stage B versus C.
- Do you have any local GPU or Apple Silicon machine? It affects where query-time embedding runs.
- Which languages do the documents and code use? Heavy CJK or formula content moves MinerU up the order.
- Is it acceptable to send document text to a third-party LLM API for entity extraction and captioning, or must that run on open models?
- Is this for you alone, or might other people use it later?

## Sources

I read search-result excerpts, not every page in full, so treat vendor benchmarks and prices as indicative and re-check before committing money. Figures were looked up on 2026-11-12. Items marked as my estimate or arithmetic are not sourced.

- Parsers: [Docling licence and models](https://idp-software.com/vendors/docling/), [docling-serve](https://pypi.org/project/docling-serve/1.19.0/), [Docling vs MinerU vs Marker](https://particula.tech/blog/docling-vs-mineru-vs-marker-pdf-parser), [MinerU overview and licence](https://www.opensourcealternatives.to/item/mineru), [MinerU 3.1.0 licence change](https://toolnavs.com/article/2457-is-mineru-worth-using-the-50k-star-pdf-to-markdown-tool-has-deployment-and-licen), [MinerU Docker image](https://hub.docker.com/r/windoze/mineru), [MinerU weights licence listing](https://huggingface.co/raoqu/mlx-mu), [PDF parser comparison](https://gitcode.csdn.net/69f1a0b10a2f6a37c5a6c44d.html)
- LlamaParse: [pricing and tiers](https://markaicode.com/pricing/llamaparse-pricing/), [plans](https://www.modern-datatools.com/tools/llamaindex/pricing), [self-hosting is Enterprise](https://developers.llamaindex.ai/python/cloud/self_hosting/), [LiteParse mention](https://gmagazine.it.com/?p=566)
- GPU: [RunPod vs Modal rates](https://lyceum.technology/magazine/modal-vs-runpod-for-serverless-gpu-inference/), [RunPod community prices](https://dupple.com/tools/runpod), [serverless break-even](https://gpuperhour.com/blog/serverless-gpu-pricing), [MinerU on RunPod](https://dev.to/sergeyshmakov/how-to-self-host-the-mineru-api-on-runpod-2ejp), [Modal credits](https://vibereference.vercel.app/cloud-and-hosting/ml-inference-gpu-platforms)
- Crawling: [Crawl4AI guide](https://www.scrapingbee.com/blog/crawl4ai/), [Crawl4AI vs Firecrawl licences](https://scrappey.com/qa/web-scraping-apis/crawl4ai-vs-firecrawl), [benchmark](https://spider.cloud/blog/firecrawl-vs-crawl4ai-vs-spider-honest-benchmark/), [Firecrawl self-host](https://fastcrw.com/blog/firecrawl-vs-crawl4ai-vs-crw)
- Graph and retrieval: [LightRAG docs](https://www.beri.net/learning/lightrag-graph-rag-docs), [GraphRAG cost and Graphiti](https://callsphere.ai/blog/vw6g-microsoft-graphrag-knowledge-graph-2026), [GraphRAG in production](https://tianpan.co/blog/2026-04-09-graphrag-production-when-vector-search-hits-ceiling), [LightRAG with open models](https://dev.co/ai/frameworks/lightrag), [hybrid search and reranking](https://wz-it.com/en/knowledge/ki/hybrid-search-reranking/), [pgvector vs Qdrant](https://www.modern-datatools.com/compare/pgvector-vs-qdrant)
- Code indexing: [code-index MCP (FTS5, tree-sitter, Qdrant)](https://glama.ai/mcp/servers/a7vulnkovz), [codeindex with SCIP](https://glama.ai/mcp/servers/v7s1hxpf8j)
- MCP clients: [Claude custom connectors](https://support.anthropic.com/en/articles/11503834-building-custom-connectors-via-remote-mcp-servers), [Claude connector network model](https://mer.vin/2026/08/local-vs-remote-mcp-claude-custom-connectors/), [ChatGPT connectors](https://zuplo.com/learn/mcp/compatibility/clients/chatgpt-connectors), [state of MCP clients](https://mcpbundles.com/blog/state-of-mcp-clients), [connecting real clients](https://nanohub-mcp.readthedocs.io/en/latest/skill/references/connecting-clients.html)
- Deployment: [MinerU on Railway](https://railway.com/deploy/mineru), [LlamaCloud usage controls](https://developers.llamaindex.ai/llamaparse/self_hosting/configuration/usage-controls/)
