"""The one place items enter the lake: scan, hash, dedupe, record location, store, enqueue."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from lake_core import ids
from lake_core.jobs import enqueue_job
from lake_core.objectstore import ObjectStore, put_original, write_package
from lake_core.secrets import redact, scan
from lake_core.titles import title_from_markdown
from sqlalchemy import Connection, Engine, text

from lake_ingest.adapter import Item
from lake_ingest.types import detect_type

BINARY_TYPES = {"pdf", "docx", "epub", "image", "audio", "video"}


@dataclass(frozen=True)
class Result:
    content_sha256: str
    new_content: bool
    new_location: bool
    quarantined: bool = False
    redactions: tuple[str, ...] = ()


def _looks_textual(data: bytes) -> bool:
    return b"\x00" not in data[:4096]


class Registrar:
    def __init__(self, engine: Engine, store: ObjectStore) -> None:
        self.engine = engine
        self.store = store

    def register(self, item: Item, *, scan_secrets: bool = True) -> Result:
        data, markdown = item.data, item.markdown
        redactions: tuple[str, ...] = ()
        stype = item.source_type or detect_type(data, item.path)
        quarantine_reasons: list[str] = []
        if scan_secrets and stype not in BINARY_TYPES and _looks_textual(data):
            body = data.decode("utf-8", errors="replace")
            findings = scan(body)
            if findings and item.on_secrets == "redact":
                clean = redact(body, findings)
                data = clean.encode()
                markdown = redact(markdown, scan(markdown)) if markdown is not None else None
                redactions = tuple(sorted({f.kind for f in findings}))
            elif findings:
                quarantine_reasons = sorted({f.kind for f in findings})
        sha = ids.content_sha256(data)
        with self.engine.begin() as c:
            source_id = self._source_id(c, item.source)
            if quarantine_reasons:
                stype = "quarantined"
            new_content = self._insert_content(c, sha, len(data), stype)
            new_location = self._insert_location(c, item, source_id, sha)
            if quarantine_reasons:
                if new_content:
                    self.store.put(f"quarantine/{sha}", data)
                    c.execute(
                        text(
                            "insert into quarantine(content_sha,reasons) "
                            "values (:h,cast(:r as jsonb))"
                        ),
                        {"h": sha, "r": json.dumps(quarantine_reasons)},
                    )
                return Result(sha, new_content, new_location, True)
            if new_content:
                self._store_and_enqueue(c, item, data, markdown, sha, stype, redactions)
        return Result(sha, new_content, new_location, False, redactions)

    def release(self, sha: str) -> None:
        """Let a held file in after review: normal storage and jobs, without the secret scan."""
        with self.engine.begin() as c:
            row = c.execute(
                text(
                    "select l.path, s.name from location l join source s on s.id=l.source_id "
                    "join quarantine q on q.content_sha=l.content_sha256 "
                    "where l.content_sha256=:h and q.status='held' limit 1"
                ),
                {"h": sha},
            ).first()
            if row is None:
                raise ValueError("not held")
            data = self.store.get(f"quarantine/{sha}")
            stype = detect_type(data, row.path)
            c.execute(
                text("update content set source_type=:t where sha256=:h"), {"t": stype, "h": sha}
            )
            c.execute(
                text("update quarantine set status='released' where content_sha=:h"), {"h": sha}
            )
            md = data.decode("utf-8", errors="replace") if stype in ("markdown", "text") else None
            item = Item(data, row.path, row.name, source_type=stype, markdown=md)
            self._store_and_enqueue(c, item, data, md, sha, stype, ())

    # --- internals -------------------------------------------------------------------------

    @staticmethod
    def _source_id(c: Connection, name: str) -> int:
        return int(
            c.execute(
                text(
                    "insert into source(name, kind) values (:n, :n) "
                    "on conflict (name) do update set name = excluded.name returning id"
                ),
                {"n": name},
            ).scalar_one()
        )

    @staticmethod
    def _insert_content(c: Connection, sha: str, size: int, stype: str) -> bool:
        return (
            c.execute(
                text(
                    "insert into content(sha256,size,source_type) values (:h,:s,:t) "
                    "on conflict do nothing"
                ),
                {"h": sha, "s": size, "t": stype},
            ).rowcount
            == 1
        )

    @staticmethod
    def _insert_location(c: Connection, item: Item, source_id: int, sha: str) -> bool:
        return (
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

    def _store_and_enqueue(
        self,
        c: Connection,
        item: Item,
        data: bytes,
        markdown: str | None,
        sha: str,
        stype: str,
        redactions: tuple[str, ...],
    ) -> None:
        put_original(self.store, sha, data)
        if markdown is not None:
            self._write_markdown_package(c, item, markdown, sha, stype, redactions)
            enqueue_job(c, "chunk", ids.package_id(sha, 1))  # chunk targets a package
        elif stype == "code":
            enqueue_job(c, "code_index", sha)  # code has its own indexer
        else:
            enqueue_job(c, "parse", sha)  # parse targets a content hash

    def _write_markdown_package(
        self,
        c: Connection,
        item: Item,
        markdown: str,
        sha: str,
        stype: str,
        redactions: tuple[str, ...],
    ) -> None:
        manifest: dict[str, Any] = {
            "content_sha256": sha,
            "rev": 1,
            "source_type": stype,
            "title": item.title or title_from_markdown(markdown, PurePosixPath(item.path).stem),
            "tier": item.tier,
            "parser": {"name": "passthrough", "version": "1"},
            "files": ["content.md"],
            "created_at": datetime.now(UTC).isoformat(),
            **item.meta,
        }
        if redactions:
            manifest["redacted"] = list(redactions)
        write_package(self.store, manifest, {"content.md": markdown.encode()})
        c.execute(
            text(
                "insert into package(id,content_sha256,rev,canonical,tier,manifest) "
                "values (:id,:h,1,true,:tier,cast(:m as jsonb))"
            ),
            {"id": ids.package_id(sha, 1), "h": sha, "tier": item.tier, "m": json.dumps(manifest)},
        )
