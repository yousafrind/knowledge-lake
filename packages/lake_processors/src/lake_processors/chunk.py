"""chunk: package markdown -> heading-aware chunks, then queue embedding."""

import re
from dataclasses import dataclass

from lake_core import ids
from lake_core.jobs import enqueue_job
from lake_core.objectstore import package_prefix
from sqlalchemy import text

from lake_processors.contract import Context

HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
MAX_CHARS = 1200


@dataclass(frozen=True)
class Piece:
    section: str
    text: str


def split_markdown(md: str, max_chars: int = MAX_CHARS) -> list[Piece]:
    """Split at headings, then pack paragraphs up to max_chars. Section = heading path."""
    stack: list[tuple[int, str]] = []
    blocks: list[tuple[str, list[str]]] = []  # (section, paragraphs)
    cur: list[str] = []
    section = ""
    para: list[str] = []

    def flush_para() -> None:
        if para:
            cur.append("\n".join(para).strip())
            para.clear()

    def flush_block() -> None:
        flush_para()
        if any(cur):
            blocks.append((section, [p for p in cur if p]))
        cur.clear()

    in_fence = False
    for line in md.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else HEADING.match(line)
        if m:
            flush_block()
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2)))
            section = " > ".join(t for _, t in stack)
        elif not line.strip() and not in_fence:
            flush_para()
        else:
            para.append(line)
    flush_block()

    pieces: list[Piece] = []
    for sec, paras in blocks:
        buf = ""
        for p in paras:
            for part in [p[i : i + max_chars] for i in range(0, len(p), max_chars)]:
                if buf and len(buf) + len(part) + 2 > max_chars:
                    pieces.append(Piece(sec, buf))
                    buf = ""
                buf = f"{buf}\n\n{part}" if buf else part
        if buf:
            pieces.append(Piece(sec, buf))
    return pieces


class ChunkProcessor:
    name = "chunk"
    version = "1"
    cost = "cpu"

    def run(self, target: str, ctx: Context) -> None:
        sha, rev = target.rsplit(":", 1)
        md = ctx.store.get(package_prefix(sha, int(rev)) + "content.md").decode()
        pieces = split_markdown(md)
        with ctx.engine.begin() as c:
            for i, piece in enumerate(pieces):
                c.execute(
                    text(
                        "insert into chunk(id,package_id,ordinal,chunker_version,section,text) "
                        "values (:id,:pkg,:o,:v,:s,:t) on conflict do nothing"
                    ),
                    {
                        "id": ids.chunk_id(target, i, self.version),
                        "pkg": target,
                        "o": i,
                        "v": self.version,
                        "s": piece.section,
                        "t": piece.text,
                    },
                )
            enqueue_job(c, "embed", target)
            enqueue_job(c, "link", target)
