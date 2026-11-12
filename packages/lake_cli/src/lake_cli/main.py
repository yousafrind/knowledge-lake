"""Operator commands. Usage: lake add <path>"""

import argparse
import sys
from pathlib import Path

from lake_core.db import make_engine
from lake_core.objectstore import ObjectStore
from lake_core.settings import load_settings
from lake_ingest.adapter import Adapter
from lake_ingest.code import CodeAdapter, record_repo
from lake_ingest.crawl import CrawlAdapter
from lake_ingest.disk import DiskAdapter
from lake_ingest.explain import explain_path_json, record_disk_root
from lake_ingest.registrar import Registrar
from lake_ingest.upload import UploadAdapter
from lake_processors.contract import Registry


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


def build_registry(
    embedder_name: str,
    gpu_url: str | None = None,
    gpu_token: str | None = None,
    rules_yaml: str = "",
) -> Registry:
    from lake_core.embedding import make_embedder
    from lake_parsers.base import Parser
    from lake_parsers.plain import PlainTextParser
    from lake_processors.chunk import ChunkProcessor
    from lake_processors.classify import ClassifyProcessor, load_rules
    from lake_processors.code_index import CodeIndexProcessor
    from lake_processors.embed import EmbedProcessor
    from lake_processors.group import GroupProcessor
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
    escalation = None
    if gpu_url:
        from lake_parsers.remote import RemoteParser

        escalation = RemoteParser(gpu_url, token=gpu_token)
    reg.add(ParseProcessor(parsers, PlainTextParser(), escalation))
    reg.add(ChunkProcessor())
    reg.add(CodeIndexProcessor())
    reg.add(LinkProcessor())
    reg.add(ClassifyProcessor(load_rules(rules_yaml)))
    embedder = make_embedder(embedder_name)
    reg.add(EmbedProcessor(embedder))
    reg.add(GroupProcessor(embedder.model))
    return reg


def _rules_text(config_dir: Path) -> str:
    f = Path(config_dir) / "rules.yaml"
    return f.read_text() if f.is_file() else ""


def work() -> str:
    from lake_processors.contract import Context
    from lake_processors.loop import run_until_idle

    s = load_settings()
    store = ObjectStore(s.s3_endpoint, s.s3_key, s.s3_secret, s.s3_bucket)
    n = run_until_idle(
        Context(make_engine(s.database_url), store),
        build_registry(s.embedder, s.gpu_url, s.gpu_token, _rules_text(s.config_dir)),
    )
    return f"{n} jobs run"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lake")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("add", help="add a file or folder").add_argument("path")
    sub.add_parser("crawl", help="crawl a website section").add_argument("url")
    sub.add_parser("disk", help="walk a folder tree with ignore rules").add_argument("path")
    sub.add_parser("explain", help="why was this path indexed or ignored").add_argument("path")
    sub.add_parser("code", help="index a git repo or code folder").add_argument("path")
    sub.add_parser("work", help="run queued jobs until none are ready")
    sub.add_parser("serve", help="run the MCP server on 127.0.0.1:8000")
    args = parser.parse_args(argv)
    if args.cmd == "add":
        print(add(args.path))
    if args.cmd == "disk":
        rules = Path(load_settings().config_dir) / "lakeignore.default"
        disk = DiskAdapter(rules.read_text() if rules.is_file() else "")
        record_disk_root(make_engine(load_settings().database_url), str(Path(args.path).resolve()))
        print(add(args.path, disk))
        print(f"{len(disk.skipped)} paths skipped")
    if args.cmd == "explain":
        s = load_settings()
        rules = Path(s.config_dir) / "lakeignore.default"
        print(
            explain_path_json(
                make_engine(s.database_url), args.path, rules.read_text() if rules.is_file() else ""
            )
        )
    if args.cmd == "code":
        s = load_settings()
        rules = Path(s.config_dir) / "lakeignore.default"
        code = CodeAdapter(rules.read_text() if rules.is_file() else "")
        print(add(args.path, code))
        if code.repo:
            record_repo(make_engine(s.database_url), code.repo)
            print(f"repo {code.repo.root} @ {code.repo.commit[:10]}: {len(code.repo.files)} files")
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
