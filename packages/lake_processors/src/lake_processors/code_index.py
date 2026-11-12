"""code_index: source file -> package (the source), symbol rows, and one chunk per symbol."""

import json
from datetime import UTC, datetime
from pathlib import PurePosixPath

from lake_code.symbols import extract_references, extract_symbols
from lake_core import ids
from lake_core.jobs import enqueue_job
from lake_core.languages import language_of
from lake_core.objectstore import get_original, write_package
from sqlalchemy import text

from lake_processors.contract import Context

CHUNKER = "code-1"
MAX_CHUNK = 1500


def fence(code: str, lang: str) -> str:
    ticks = "`" * max(3, max((len(r) for r in code.split("\n") if set(r) == {"`"}), default=0) + 1)
    return f"{ticks}{lang}\n{code}\n{ticks}\n"


class CodeIndexProcessor:
    name = "code_index"
    version = "2"
    cost = "cpu"

    def run(self, target: str, ctx: Context) -> None:
        with ctx.engine.connect() as c:
            path = c.execute(
                text("select path from location where content_sha256=:h order by seen_at limit 1"),
                {"h": target},
            ).scalar_one()
        lang = language_of(path)
        if lang is None:
            raise ValueError(f"no language for {path}")
        source = get_original(ctx.store, target)
        code = source.decode("utf-8", errors="replace")
        symbols = extract_symbols(lang, source)
        refs, imports = extract_references(lang, source)
        lines = code.splitlines()
        pid = ids.package_id(target, 1)
        manifest = {
            "content_sha256": target,
            "rev": 1,
            "source_type": "code",
            "title": PurePosixPath(path).name,
            "tier": "original",
            "parser": {"name": "tree-sitter", "version": "1"},
            "language": lang,
            "files": ["content.md"],
            "assets": 0,
            "qa": {},
            "created_at": datetime.now(UTC).isoformat(),
        }
        with ctx.engine.begin() as c:
            exists = c.execute(text("select 1 from package where id=:i"), {"i": pid}).first()
            if not exists:
                write_package(ctx.store, manifest, {"content.md": fence(code, lang).encode()})
                c.execute(
                    text(
                        "insert into package(id,content_sha256,rev,canonical,manifest) "
                        "values (:i,:h,1,true,cast(:m as jsonb)) on conflict do nothing"
                    ),
                    {"i": pid, "h": target, "m": json.dumps(manifest)},
                )
            for r in refs:
                c.execute(
                    text(
                        "insert into code_ref(content_sha,name,line,kind) values (:h,:n,:l,:k) "
                        "on conflict do nothing"
                    ),
                    {"h": target, "n": r.name, "l": r.line, "k": r.kind},
                )
            for module in imports:
                c.execute(
                    text(
                        "insert into code_import(content_sha,module) values (:h,:m) "
                        "on conflict do nothing"
                    ),
                    {"h": target, "m": module},
                )
            pieces = []
            for s in symbols:
                c.execute(
                    text(
                        "insert into code_symbol(content_sha,name,kind,signature,doc,"
                        "start_line,end_line,parent) values (:h,:n,:k,:s,:d,:a,:b,:p) "
                        "on conflict do nothing"
                    ),
                    {
                        "h": target,
                        "n": s.name,
                        "k": s.kind,
                        "s": s.signature,
                        "d": s.doc,
                        "a": s.start_line,
                        "b": s.end_line,
                        "p": s.parent,
                    },
                )
                body = "\n".join(lines[s.start_line - 1 : s.end_line])
                pieces.append((s.name, f"{path}\n{s.doc}\n{body}"[:MAX_CHUNK]))
            if not pieces:  # no symbols (config, script): index the head of the file
                pieces.append((PurePosixPath(path).name, f"{path}\n" + "\n".join(lines[:60])))
            for i, (section, body) in enumerate(pieces):
                c.execute(
                    text(
                        "insert into chunk(id,package_id,ordinal,chunker_version,section,text) "
                        "values (:id,:p,:o,:v,:s,:t) on conflict do nothing"
                    ),
                    {
                        "id": ids.chunk_id(pid, i, CHUNKER),
                        "p": pid,
                        "o": i,
                        "v": CHUNKER,
                        "s": section,
                        "t": body,
                    },
                )
            enqueue_job(c, "embed", pid)
            enqueue_job(c, "classify", pid)
