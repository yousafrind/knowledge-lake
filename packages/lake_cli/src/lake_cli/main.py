"""Operator commands. Usage: lake add <path>"""

import argparse
import sys

from lake_core.db import make_engine
from lake_core.objectstore import ObjectStore
from lake_core.settings import load_settings
from lake_ingest.adapter import Adapter
from lake_ingest.crawl import CrawlAdapter
from lake_ingest.registrar import Registrar
from lake_ingest.upload import UploadAdapter


def add(path: str, adapter: Adapter | None = None) -> str:
    s = load_settings()
    store = ObjectStore(s.s3_endpoint, s.s3_key, s.s3_secret, s.s3_bucket)
    store.ensure_bucket()
    reg = Registrar(make_engine(s.database_url), store)
    seen = new_content = new_locations = 0
    for item in (adapter or UploadAdapter()).scan(path):
        r = reg.register(item)
        seen += 1
        new_content += r.new_content
        new_locations += r.new_location
    return f"{seen} files, {new_content} new content, {new_locations} new locations"


def build_registry(embedder_name: str):  # type: ignore[no-untyped-def]
    from lake_core.embedding import make_embedder
    from lake_parsers.base import Parser
    from lake_parsers.plain import PlainTextParser
    from lake_processors.chunk import ChunkProcessor
    from lake_processors.contract import Registry
    from lake_processors.embed import EmbedProcessor
    from lake_processors.link import LinkProcessor
    from lake_processors.parse import ParseProcessor

    parsers: dict[str, Parser] = {}
    try:  # Docling is optional; without it everything falls back to the plain parser
        from lake_parsers.docling_backend import DoclingParser

        docling = DoclingParser()
        parsers = {t: docling for t in ("pdf", "docx", "html", "epub")}
    except Exception:
        pass
    reg = Registry()
    reg.add(ParseProcessor(parsers, PlainTextParser()))
    reg.add(ChunkProcessor())
    reg.add(LinkProcessor())
    reg.add(EmbedProcessor(make_embedder(embedder_name)))
    return reg


def work() -> str:
    from lake_processors.contract import Context
    from lake_processors.loop import run_until_idle

    s = load_settings()
    store = ObjectStore(s.s3_endpoint, s.s3_key, s.s3_secret, s.s3_bucket)
    n = run_until_idle(Context(make_engine(s.database_url), store), build_registry(s.embedder))
    return f"{n} jobs run"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lake")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("add", help="add a file or folder").add_argument("path")
    sub.add_parser("crawl", help="crawl a website section").add_argument("url")
    sub.add_parser("work", help="run queued jobs until none are ready")
    sub.add_parser("serve", help="run the MCP server on 127.0.0.1:8000")
    args = parser.parse_args(argv)
    if args.cmd == "add":
        print(add(args.path))
    if args.cmd == "crawl":
        print(add(args.url, CrawlAdapter()))
    if args.cmd == "work":
        print(work())
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("lake_server.app:build_app", factory=True, host="127.0.0.1", port=8000)
    return 0


if __name__ == "__main__":
    sys.exit(main())
