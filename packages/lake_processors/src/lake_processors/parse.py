"""parse: original bytes -> markdown package (rev N), then queue chunking."""

import json
from datetime import UTC, datetime
from pathlib import PurePosixPath

from lake_core import ids
from lake_core.jobs import enqueue_job
from lake_core.objectstore import get_original, write_package
from lake_core.titles import title_from_markdown
from lake_parsers.base import Parser
from lake_parsers.qa import score
from sqlalchemy import text

from lake_processors.contract import Context


class ParseProcessor:
    name = "parse"
    version = "1"
    cost = "cpu"

    def __init__(
        self, parsers: dict[str, Parser], default: Parser, escalation: Parser | None = None
    ) -> None:
        self.parsers = parsers  # source_type -> parser
        self.default = default
        self.escalation = escalation  # stronger parser, tried when QA fails

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
        original = get_original(ctx.store, target)
        parsed = parser.parse(original, filename)
        parsed.qa = score(parsed, len(original), stype)
        if not parsed.qa["ok"] and self.escalation is not None:
            first_reasons = parsed.qa["reasons"]
            try:
                better = self.escalation.parse(original, filename)
                better.qa = score(better, len(original), stype)
                better.qa["escalated_to"] = self.escalation.name
                better.qa["first_failure"] = first_reasons
                if better.qa["ok"] or better.qa["chars"] > parsed.qa["chars"]:
                    parsed, parser = better, self.escalation
            except Exception as e:  # keep the first result, flag it for review
                parsed.qa["escalation_error"] = f"{type(e).__name__}: {e}"
        parsed.qa["needs_review"] = not parsed.qa["ok"]
        files = {
            "content.md": parsed.markdown.encode(),
            "structure.json": json.dumps(parsed.structure).encode(),
            **parsed.assets,
        }
        manifest = {
            "content_sha256": target,
            "rev": 1,
            "source_type": stype,
            "title": title_from_markdown(parsed.markdown, PurePosixPath(filename).stem),
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
