"""Queries behind the code browser and chat list."""

import html
from typing import Any

from lake_core.objectstore import ObjectStore, get_original
from sqlalchemy import Engine, text

from lake_server.code_tools import LATEST


def repos(engine: Engine) -> list[Any]:
    with engine.connect() as c:
        return list(
            c.execute(
                text(
                    f"select l.repo, count(*) files, (select root from code_repo r where r.id=l.repo_id) "
                    f"as root from ({LATEST}) l group by l.repo, l.repo_id order by l.repo"
                )
            ).all()
        )


def repo_listing(engine: Engine, repo: str, prefix: str) -> tuple[list[dict[str, Any]], list[Any]]:
    base = prefix.strip("/")
    base = base + "/" if base else ""
    dirs: dict[str, int] = {}
    files: list[Any] = []
    with engine.connect() as c:
        rows = c.execute(
            text(f"select path from ({LATEST}) l where l.repo=:r order by path"), {"r": repo}
        ).all()
    for (path,) in rows:
        if not path.startswith(base):
            continue
        rest = path[len(base) :]
        if "/" in rest:
            name = rest.split("/", 1)[0]
            dirs[name] = dirs.get(name, 0) + 1
        else:
            files.append({"name": rest, "path": path})
    return [{"name": n, "path": base + n, "count": k} for n, k in sorted(dirs.items())], files


def file_view(engine: Engine, store: ObjectStore, repo: str, path: str) -> dict[str, Any] | None:
    with engine.connect() as c:
        f = c.execute(
            text(f"select content_sha from ({LATEST}) l where l.repo=:r and l.path=:p"),
            {"r": repo, "p": path},
        ).first()
        if f is None:
            return None
        symbols = c.execute(
            text(
                "select name, kind, signature, start_line from code_symbol "
                "where content_sha=:h order by start_line"
            ),
            {"h": f.content_sha},
        ).all()
    source = get_original(store, f.content_sha).decode(errors="replace")
    lines = [(i + 1, html.escape(line)) for i, line in enumerate(source.splitlines())]
    return {"sha": f.content_sha, "symbols": symbols, "lines": lines}


def chats(engine: Engine, origin: str | None, tag: str | None) -> list[Any]:
    with engine.connect() as c:
        return list(
            c.execute(
                text(
                    "select p.content_sha256 as sha, p.manifest->>'title' as title, "
                    "p.manifest->>'origin' as origin, p.manifest->>'created_at' as saved, "
                    "(p.manifest ? 'redacted') as redacted, "
                    "coalesce((select array_agg(substr(key, 5) order by key) from label "
                    " where content_sha=p.content_sha256 and key like 'tag:%'), '{}') as tags, "
                    "(select path from location where content_sha256=p.content_sha256 limit 1) as path "
                    "from package p join content c on c.sha256=p.content_sha256 "
                    "where p.canonical and c.source_type='chat' "
                    "and (cast(:o as text) is null or p.manifest->>'origin' = :o) "
                    "and (cast(:t as text) is null or exists (select 1 from label "
                    " where content_sha=p.content_sha256 and key = 'tag:' || :t)) "
                    "order by p.manifest->>'created_at' desc limit 200"
                ),
                {"o": origin or None, "t": tag or None},
            ).all()
        )
