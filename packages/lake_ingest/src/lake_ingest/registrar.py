"""The one place items enter the lake: hash, dedupe, record location, store, enqueue."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath

from lake_core import ids
from lake_core.jobs import enqueue_job
from lake_core.objectstore import ObjectStore, put_original, write_package
from sqlalchemy import Engine, text

from lake_ingest.adapter import Item

SUFFIX_TYPES = {
    ".pdf": "pdf",
    ".md": "markdown",
    ".txt": "text",
    ".html": "html",
    ".htm": "html",
    ".docx": "docx",
    ".epub": "epub",
    ".json": "json",
}


@dataclass(frozen=True)
class Result:
    content_sha256: str
    new_content: bool
    new_location: bool


def detect_type(item: Item) -> str:
    return item.source_type or SUFFIX_TYPES.get(PurePosixPath(item.path).suffix.lower(), "binary")


class Registrar:
    def __init__(self, engine: Engine, store: ObjectStore) -> None:
        self.engine = engine
        self.store = store

    def register(self, item: Item) -> Result:
        sha = ids.content_sha256(item.data)
        stype = detect_type(item)
        with self.engine.begin() as c:
            source_id = c.execute(
                text(
                    "insert into source(name, kind) values (:n, :n) "
                    "on conflict (name) do update set name = excluded.name returning id"
                ),
                {"n": item.source},
            ).scalar_one()
            new_content = (
                c.execute(
                    text(
                        "insert into content(sha256,size,source_type) values (:h,:s,:t) "
                        "on conflict do nothing"
                    ),
                    {"h": sha, "s": len(item.data), "t": stype},
                ).rowcount
                == 1
            )
            new_location = (
                c.execute(
                    text(
                        "insert into location(id,source_id,path,content_sha256,mtime) "
                        "values (:id,:src,:p,:h,:m) on conflict do nothing"
                    ),
                    {
                        "id": ids.location_id(item.source, item.path, sha),
                        "src": source_id,
                        "p": item.path,
                        "h": sha,
                        "m": item.mtime,
                    },
                ).rowcount
                == 1
            )
            if new_content:
                put_original(self.store, sha, item.data)
                if item.markdown is not None:
                    self._write_markdown_package(c, item, sha, stype)
                if item.markdown is not None:
                    enqueue_job(c, "chunk", ids.package_id(sha, 1))  # chunk targets a package
                else:
                    enqueue_job(c, "parse", sha)  # parse targets a content hash
        return Result(sha, new_content, new_location)

    def _write_markdown_package(self, c, item: Item, sha: str, stype: str) -> None:  # type: ignore[no-untyped-def]
        assert item.markdown is not None
        manifest = {
            "content_sha256": sha,
            "rev": 1,
            "source_type": stype,
            "title": PurePosixPath(item.path).stem,
            "tier": "original",
            "parser": {"name": "passthrough", "version": "1"},
            "files": ["content.md"],
            "created_at": datetime.now(UTC).isoformat(),
        }
        write_package(self.store, manifest, {"content.md": item.markdown.encode()})
        c.execute(
            text(
                "insert into package(id,content_sha256,rev,canonical,manifest) "
                "values (:id,:h,1,true,cast(:m as jsonb))"
            ),
            {"id": ids.package_id(sha, 1), "h": sha, "m": json.dumps(manifest)},
        )
