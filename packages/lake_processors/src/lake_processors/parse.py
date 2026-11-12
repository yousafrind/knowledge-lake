"""parse: original bytes -> markdown package (rev N), then queue chunking."""

import json
from datetime import UTC, datetime
from pathlib import PurePosixPath

from lake_core import ids
from lake_core.jobs import enqueue_job
from lake_core.objectstore import get_original, write_package
from lake_parsers.base import Parser
from sqlalchemy import text

from lake_processors.contract import Context


class ParseProcessor:
    name = "parse"
    version = "1"
    cost = "cpu"

    def __init__(self, parsers: dict[str, Parser], default: Parser) -> None:
        self.parsers = parsers  # source_type -> parser
        self.default = default

    def run(self, target: str, ctx: Context) -> None:
        with ctx.engine.begin() as c:
            row = c.execute(
                text(
                    "select c.source_type, "
                    "(select path from location where content_sha256=c.sha256 limit 1), "
                    "(select max(rev) from package where content_sha256=c.sha256) "
                    "from content c where c.sha256=:h"
                ),
                {"h": target},
            ).one()
            stype, path, last_rev = row
            if last_rev is not None:
                enqueue_job(c, "chunk", ids.package_id(target, last_rev))  # idempotent rerun
                return
        parser = self.parsers.get(stype, self.default)
        filename = PurePosixPath(path or target).name
        parsed = parser.parse(get_original(ctx.store, target), filename)
        files = {
            "content.md": parsed.markdown.encode(),
            "structure.json": json.dumps(parsed.structure).encode(),
            **parsed.assets,
        }
        manifest = {
            "content_sha256": target,
            "rev": 1,
            "source_type": stype,
            "title": PurePosixPath(filename).stem,
            "tier": "original",
            "parser": {"name": parser.name, "version": parser.version},
            "files": list(files),
            "assets": len(parsed.assets),
            "qa": parsed.qa,
            "created_at": datetime.now(UTC).isoformat(),
        }
        write_package(ctx.store, manifest, files)
        pid = ids.package_id(target, 1)
        with ctx.engine.begin() as c:
            c.execute(
                text(
                    "insert into package(id,content_sha256,rev,canonical,manifest) "
                    "values (:id,:h,1,true,cast(:m as jsonb)) on conflict do nothing"
                ),
                {"id": pid, "h": target, "m": json.dumps(manifest)},
            )
            enqueue_job(c, "chunk", pid)
