"""Code tools (scope `code:read`). References are name matches, not precise (see register)."""

import json
import re
from typing import Any

from lake_core.embedding import Embedder
from lake_core.objectstore import ObjectStore, get_original
from lake_retrieval.search import Filters, search
from sqlalchemy import Connection, Engine, text

MAX_LINES = 400

# newest indexed commit per repo, joined to its files
LATEST = """
  select f.repo_id, f.path, f.content_sha, r.name as repo
  from code_repo_file f join code_repo r on r.id = f.repo_id
  where f.commit_sha = (select commit_sha from code_repo_file f2 where f2.repo_id = f.repo_id
                        order by seen_at desc limit 1)
"""


def _repo_clause(repo: str | None) -> str:
    return " and (l.repo = :repo or l.repo is null)" if repo else ""


def _file(c: Connection, path: str, repo: str | None) -> Any:
    row = c.execute(
        text(
            f"select * from ({LATEST}) l where l.path = :p {'and l.repo = :repo' if repo else ''}"
            " limit 1"
        ),
        {"p": path, "repo": repo},
    ).first()
    if row is None:
        raise ValueError(f"no indexed file {path!r}" + (f" in repo {repo!r}" if repo else ""))
    return row


def find_symbol_json(
    engine: Engine, name: str, repo: str | None = None, kind: str | None = None
) -> str:
    with engine.connect() as c:
        rows = c.execute(
            text(
                f"select l.repo, l.path, s.name, s.kind, s.signature, s.doc, s.start_line, s.end_line "
                f"from code_symbol s join ({LATEST}) l on l.content_sha = s.content_sha "
                "where (s.name = :n or s.name like '%.' || :n or similarity(s.name, :n) > 0.5) "
                "and (cast(:repo as text) is null or l.repo = :repo) "
                "and (cast(:kind as text) is null or s.kind = :kind) "
                "order by (s.name = :n) desc, similarity(s.name, :n) desc limit 25"
            ),
            {"n": name, "repo": repo, "kind": kind},
        ).all()
    return json.dumps({"symbols": [r._asdict() for r in rows]})


def find_references_json(engine: Engine, name: str, repo: str | None = None) -> str:
    short = name.rsplit(".", 1)[-1]
    with engine.connect() as c:
        rows = c.execute(
            text(
                f"select l.repo, l.path, r.line, r.kind from code_ref r "
                f"join ({LATEST}) l on l.content_sha = r.content_sha "
                "where r.name = :n and (cast(:repo as text) is null or l.repo = :repo) "
                "order by l.repo, l.path, r.line limit 200"
            ),
            {"n": short, "repo": repo},
        ).all()
    return json.dumps(
        {
            "precision": "name match (tree-sitter); not scope-aware",
            "references": [r._asdict() for r in rows],
        }
    )


def file_outline_json(engine: Engine, path: str, repo: str | None = None) -> str:
    with engine.connect() as c:
        f = _file(c, path, repo)
        syms = c.execute(
            text(
                "select name, kind, signature, start_line, end_line from code_symbol "
                "where content_sha = :h order by start_line"
            ),
            {"h": f.content_sha},
        ).all()
    return json.dumps({"repo": f.repo, "path": path, "symbols": [s._asdict() for s in syms]})


def get_file_json(
    engine: Engine,
    store: ObjectStore,
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
    repo: str | None = None,
) -> str:
    with engine.connect() as c:
        f = _file(c, path, repo)
    lines = get_original(store, f.content_sha).decode(errors="replace").splitlines()
    start = max(1, start_line)
    end = min(len(lines), end_line or len(lines), start + MAX_LINES - 1)
    return json.dumps(
        {
            "repo": f.repo,
            "path": path,
            "start_line": start,
            "end_line": end,
            "total_lines": len(lines),
            "text": "\n".join(lines[start - 1 : end]),
        }
    )


def repo_map_json(engine: Engine, repo: str | None = None, max_chars: int = 6000) -> str:
    """Files ranked by how often their symbols are referenced elsewhere, with top-level defs."""
    with engine.connect() as c:
        files = c.execute(
            text(
                f"""
                select l.repo, l.path, l.content_sha,
                  (select count(*) from code_ref r
                     join code_symbol s on s.content_sha = l.content_sha and s.parent is null
                    where r.name = s.name and r.content_sha <> l.content_sha) as inbound
                from ({LATEST}) l where cast(:repo as text) is null or l.repo = :repo
                order by inbound desc, l.path
                """
            ),
            {"repo": repo},
        ).all()
        out: list[dict[str, Any]] = []
        used = 0
        for f in files:
            syms = c.execute(
                text(
                    "select signature from code_symbol where content_sha = :h and parent is null "
                    "order by start_line"
                ),
                {"h": f.content_sha},
            ).all()
            if not syms:
                continue
            block = f"{f.repo}/{f.path}\n" + "\n".join(f"  {s[0]}" for s in syms)
            if out and used + len(block) > max_chars:
                break
            out.append(
                {"path": f"{f.repo}/{f.path}", "referenced_by_other_files": f.inbound, "map": block}
            )
            used += len(block)
    return json.dumps({"files": out})


def code_search_json(
    engine: Engine, embedder: Embedder, query: str, repo: str | None = None
) -> str:
    sym = json.loads(find_symbol_json(engine, query, repo))["symbols"][:5]
    hits = search(engine, embedder, query, limit=10, filters=Filters(source_types=["code"]))
    return json.dumps(
        {
            "symbol_matches": sym,
            "results": [
                {
                    "id": h.citation["uri"],
                    "path": h.citation["location"],
                    "symbol": h.citation["section"],
                    "text": h.text,
                    "score": round(h.score, 5),
                }
                for h in hits
            ],
        }
    )


def dependency_docs_json(engine: Engine, store: ObjectStore, repo: str | None = None) -> str:
    """For each dependency in the repo's manifests, the documentation we hold about it."""
    from lake_code.manifests import parse_manifest, search_terms

    with engine.connect() as c:
        manifests = c.execute(
            text(
                f"select l.repo, l.path, l.content_sha from ({LATEST}) l "
                "where l.path ~ '(^|/)(pyproject\\.toml|requirements\\.txt|package\\.json|"
                "Cargo\\.toml|go\\.mod)$' and (cast(:repo as text) is null or l.repo = :repo)"
            ),
            {"repo": repo},
        ).all()
        result = []
        for m in manifests:
            try:
                deps = parse_manifest(m.path, get_original(store, m.content_sha).decode())
            except (ValueError, KeyError):
                continue  # unreadable manifest: skip it, do not fail the whole tool
            for dep in deps:
                terms = search_terms(dep)
                docs = c.execute(
                    text(
                        "select distinct p.content_sha256 as sha, p.manifest->>'title' as title, "
                        "l.path as location, "
                        "(lower(p.manifest->>'title') = any(:t))::int * 2 + "
                        "(lower(l.path) ~ ('(^|[/._-])(' || :alt || ')([/._-]|$)'))::int as score "
                        "from package p join content c on c.sha256 = p.content_sha256 "
                        "join location l on l.content_sha256 = p.content_sha256 "
                        "where p.canonical and c.source_type not in ('code','manifest') "
                        "and (lower(p.manifest->>'title') ~ ('(^|[^a-z0-9])(' || :alt || ')([^a-z0-9]|$)') "
                        "or lower(l.path) ~ ('(^|[/._-])(' || :alt || ')([/._-]|$)')) "
                        "order by score desc, title limit 3"
                    ),
                    {"t": terms, "alt": "|".join(re.escape(t) for t in terms)},
                ).all()
                result.append(
                    {
                        "repo": m.repo,
                        "manifest": m.path,
                        "dependency": dep.name,
                        "spec": dep.spec,
                        "ecosystem": dep.ecosystem,
                        "dev": dep.dev,
                        "docs": [
                            {"id": f"lake://{d.sha}", "title": d.title, "location": d.location}
                            for d in docs
                        ],
                    }
                )
    return json.dumps({"dependencies": result})
