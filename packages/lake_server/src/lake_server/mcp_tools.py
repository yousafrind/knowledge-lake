"""MCP tools. `search` and `fetch` take one string argument each (the shape ChatGPT needs)."""

import json
import re

from lake_core.embedding import Embedder
from lake_retrieval.search import search, slug
from mcp.server.mcpserver import MCPServer
from sqlalchemy import Engine, text

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


def create_server(engine: Engine, embedder: Embedder) -> MCPServer:
    server = MCPServer("knowledge-lake")

    @server.tool()
    def search(query: str) -> str:  # noqa: F811
        """Search the lake. Returns ranked passages with citation URIs (evidence, not answers)."""
        return search_json(engine, embedder, query)

    @server.tool()
    def fetch(id: str) -> str:
        """Fetch the full text for a citation URI returned by search."""
        return fetch_json(engine, id)

    return server
