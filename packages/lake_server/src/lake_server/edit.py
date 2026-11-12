"""Edits never change a package: a correction is a new revision (tier 'derived')."""

import json
from datetime import UTC, datetime

from lake_core import ids
from lake_core.jobs import enqueue_job
from lake_core.objectstore import ObjectStore, package_prefix, write_package
from lake_core.titles import title_from_markdown
from sqlalchemy import Engine, text


def save_revision(engine: Engine, store: ObjectStore, sha: str, markdown: str) -> int:
    """Write the next revision of a document, make it canonical, queue re-chunking."""
    with engine.begin() as c:
        cur = c.execute(
            text(
                "select rev, manifest from package where content_sha256=:h "
                "order by rev desc limit 1"
            ),
            {"h": sha},
        ).first()
        if cur is None:
            raise ValueError("unknown document")
        rev = cur.rev + 1
        manifest = {
            **cur.manifest,
            "rev": rev,
            "tier": "derived",
            "title": title_from_markdown(markdown, cur.manifest.get("title", sha[:8])),
            "parser": {"name": "gui-edit", "version": "1"},
            "files": ["content.md"],
            "assets": 0,
            "qa": {},
            "edited_by": "gui",
            "created_at": datetime.now(UTC).isoformat(),
        }
        write_package(store, manifest, {"content.md": markdown.encode()})
        c.execute(text("update package set canonical=false where content_sha256=:h"), {"h": sha})
        pid = ids.package_id(sha, rev)
        c.execute(
            text(
                "insert into package(id,content_sha256,rev,canonical,tier,manifest) "
                "values (:id,:h,:r,true,'derived',cast(:m as jsonb))"
            ),
            {"id": pid, "h": sha, "r": rev, "m": json.dumps(manifest)},
        )
        enqueue_job(c, "chunk", pid)
    return int(rev)


def current_markdown(engine: Engine, store: ObjectStore, sha: str) -> str:
    with engine.connect() as c:
        rev = c.execute(
            text("select rev from package where content_sha256=:h and canonical"), {"h": sha}
        ).scalar_one_or_none()
    if rev is None:
        raise ValueError("unknown document")
    return store.get(package_prefix(sha, rev) + "content.md").decode()


def set_manual_label(engine: Engine, sha: str, key: str, value: str) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "insert into label(content_sha,key,value,source) values (:h,:k,:v,'manual') "
                "on conflict (content_sha,key,source) do update set value=excluded.value"
            ),
            {"h": sha, "k": key.strip(), "v": value.strip()},
        )
