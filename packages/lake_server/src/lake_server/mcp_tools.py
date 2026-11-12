"""MCP tools. `search` and `fetch` take one string argument each (the shape ChatGPT needs)."""

import json
import re

from lake_core.embedding import Embedder
from lake_core.objectstore import ObjectStore
from lake_ingest.explain import explain_path_json
from lake_retrieval.search import Filters, search, slug
from mcp.server.mcpserver import MCPServer
from sqlalchemy import Engine, text

from lake_server import code_tools

URI = re.compile(r"^lake://([0-9a-f]{64})#(\d+)/(.*)$")


def search_json(engine: Engine, embedder: Embedder, query: str) -> str:
    hits = search(engine, embedder, query)
    results = [
        {
            "id": h.citation["uri"],
            "title": f"{h.citation['title']} — {h.citation['section'] or 'top'}",
            "url": h.citation["uri"],
            "text": h.text,
            "tier": h.citation["tier"],
            "location": h.citation["location"],
            "score": round(h.score, 5),
        }
        for h in hits
    ]
    return json.dumps({"results": results})


def fetch_json(engine: Engine, uri: str) -> str:
    m = URI.match(uri)
    if not m:
        raise ValueError("id must be a lake:// citation URI")
    sha, rev, sec = m.group(1), int(m.group(2)), m.group(3)
    with engine.connect() as c:
        pkg = c.execute(
            text(
                "select id, manifest->>'title', tier from package "
                "where content_sha256=:h and rev=:r"
            ),
            {"h": sha, "r": rev},
        ).first()
        if pkg is None:
            raise ValueError("unknown document")
        rows = c.execute(
            text("select section, text from chunk where package_id=:p order by ordinal"),
            {"p": pkg[0]},
        ).all()
    parts = [r.text for r in rows if not sec or slug(r.section or "") == sec]
    if not parts:
        raise ValueError("unknown section")
    return json.dumps(
        {
            "id": uri,
            "title": pkg[1],
            "text": "\n\n".join(parts),
            "url": uri,
            "metadata": {"tier": pkg[2]},
        }
    )


def _sha(ref: str) -> str:
    m = URI.match(ref)
    sha = m.group(1) if m else ref
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("id must be a content hash or a lake:// URI")
    return sha


def query_json(
    engine: Engine,
    embedder: Embedder,
    query: str,
    source_type: str | None = None,
    tier: str | None = None,
    limit: int = 10,
) -> str:
    f = Filters(source_types=[source_type] if source_type else None, tiers=[tier] if tier else None)
    hits = search(engine, embedder, query, limit=max(1, min(limit, 50)), filters=f)
    return json.dumps(
        {
            "results": [
                {
                    "id": h.citation["uri"],
                    "text": h.text,
                    "score": round(h.score, 5),
                    "citation": h.citation,
                }
                for h in hits
            ]
        }
    )


def get_document_json(engine: Engine, ref: str) -> str:
    sha = _sha(ref)
    with engine.connect() as c:
        pkgs = c.execute(
            text(
                "select rev, canonical, tier, manifest from package where content_sha256=:h "
                "order by rev desc"
            ),
            {"h": sha},
        ).all()
        if not pkgs:
            raise ValueError("unknown document")
        cur = next((p for p in pkgs if p.canonical), pkgs[0])
        sections = [
            r[0]
            for r in c.execute(
                text(
                    "select section from chunk where package_id=:p and section <> '' "
                    "group by section order by min(ordinal)"
                ),
                {"p": f"{sha}:{cur.rev}"},
            )
        ]
    return json.dumps(
        {
            "id": f"lake://{sha}#{cur.rev}",
            "manifest": cur.manifest,
            "outline": sections,
            "revisions": [{"rev": p.rev, "tier": p.tier, "canonical": p.canonical} for p in pkgs],
        }
    )


def resolve_source_json(engine: Engine, ref: str) -> str:
    sha = _sha(ref)
    with engine.connect() as c:
        rows = c.execute(
            text(
                "select s.name as source, l.path, l.mtime, l.seen_at from location l "
                "join source s on s.id=l.source_id where l.content_sha256=:h order by l.path"
            ),
            {"h": sha},
        ).all()
    return json.dumps(
        {
            "content_sha256": sha,
            "locations": [
                {
                    "source": r.source,
                    "path": r.path,
                    "mtime": r.mtime and r.mtime.isoformat(),
                    "seen_at": r.seen_at.isoformat(),
                }
                for r in rows
            ],
        }
    )


def neighbors_json(engine: Engine, embedder: Embedder, ref: str, limit: int = 5) -> str:
    sha = _sha(ref)
    with engine.connect() as c:
        out = c.execute(
            text("select dst_ref, dst_sha, anchor from edge where src_sha=:h"), {"h": sha}
        ).all()
        inn = c.execute(text("select src_sha from edge where dst_sha=:h"), {"h": sha}).all()
        similar = c.execute(
            text(
                """
                with centroid as (
                  select avg(e.vec) as v from embedding e
                  join chunk ch on ch.id=e.chunk_id join package p on p.id=ch.package_id
                  where p.content_sha256=:h and p.canonical and e.model=:m)
                select p.content_sha256 as sha, p.manifest->>'title' as title,
                       min(e.vec <=> (select v from centroid)) as dist
                from embedding e join chunk ch on ch.id=e.chunk_id
                join package p on p.id=ch.package_id and p.canonical
                where e.model=:m and p.content_sha256 <> :h and (select v from centroid) is not null
                group by p.content_sha256, p.manifest->>'title' order by dist limit :n
                """
            ),
            {"h": sha, "m": embedder.model, "n": limit},
        ).all()
    return json.dumps(
        {
            "links_out": [{"ref": r.dst_ref, "id": r.dst_sha, "anchor": r.anchor} for r in out],
            "linked_from": [r.src_sha for r in inn],
            "similar": [
                {"id": r.sha, "title": r.title, "distance": round(float(r.dist), 4)}
                for r in similar
            ],
        }
    )


def create_server(
    engine: Engine,
    embedder: Embedder,
    default_rules: str = "",
    store: ObjectStore | None = None,
) -> MCPServer:
    server = MCPServer("knowledge-lake")

    @server.tool()
    def search(query: str) -> str:  # noqa: F811
        """Search the lake. Returns ranked passages with citation URIs (evidence, not answers)."""
        return search_json(engine, embedder, query)

    @server.tool()
    def fetch(id: str) -> str:
        """Fetch the full text for a citation URI returned by search."""
        return fetch_json(engine, id)

    @server.tool()
    def query(
        query: str, source_type: str | None = None, tier: str | None = None, limit: int = 10
    ) -> str:
        """Filtered search. source_type e.g. pdf/markdown/html; tier is original or derived."""
        return query_json(engine, embedder, query, source_type, tier, limit)

    @server.tool()
    def get_document(id: str) -> str:
        """Manifest, outline and revisions for a document (content hash or lake:// URI)."""
        return get_document_json(engine, id)

    @server.tool()
    def neighbors(id: str, limit: int = 5) -> str:
        """Documents linked to, linked from, or similar to this one."""
        return neighbors_json(engine, embedder, id, limit)

    @server.tool()
    def resolve_source(id: str) -> str:
        """Every place (source and path) where this content was found."""
        return resolve_source_json(engine, id)

    @server.tool()
    def explain_path(path: str) -> str:
        """Admin: why a path was indexed, ignored or labelled (needs the admin scope)."""
        return explain_path_json(engine, path, default_rules)

    @server.tool()
    def code_search(query: str, repo: str | None = None) -> str:
        """Search code: symbol-name matches first, then hybrid search over symbol chunks."""
        return code_tools.code_search_json(engine, embedder, query, repo)

    @server.tool()
    def code_find_symbol(name: str, repo: str | None = None, kind: str | None = None) -> str:
        """Where is a function/class/method defined? Name may be qualified (Repo.save)."""
        return code_tools.find_symbol_json(engine, name, repo, kind)

    @server.tool()
    def code_find_references(name: str, repo: str | None = None) -> str:
        """Places that mention a symbol (name match, not scope-aware)."""
        return code_tools.find_references_json(engine, name, repo)

    @server.tool()
    def code_file_outline(path: str, repo: str | None = None) -> str:
        """Symbols in a file with signatures and line ranges (path relative to the repo root)."""
        return code_tools.file_outline_json(engine, path, repo)

    @server.tool()
    def code_get_file(
        path: str, start_line: int = 1, end_line: int | None = None, repo: str | None = None
    ) -> str:
        """Read a file or a line range (at most 400 lines per call)."""
        if store is None:
            raise ValueError("object store not configured")
        return code_tools.get_file_json(engine, store, path, start_line, end_line, repo)

    @server.tool()
    def code_repo_map(repo: str | None = None, max_chars: int = 6000) -> str:
        """Orientation: files ranked by how much other code refers to them, with top-level defs."""
        return code_tools.repo_map_json(engine, repo, max_chars)

    @server.tool()
    def code_dependency_docs(repo: str | None = None) -> str:
        """Dependencies from the repo's manifests, each with matching documentation in the lake."""
        if store is None:
            raise ValueError("object store not configured")
        return code_tools.dependency_docs_json(engine, store, repo)

    return server
