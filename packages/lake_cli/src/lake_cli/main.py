"""Operator commands. Usage: lake add <path>"""

import argparse
import sys

from lake_core.db import make_engine
from lake_core.objectstore import ObjectStore
from lake_core.settings import load_settings
from lake_ingest.registrar import Registrar
from lake_ingest.upload import UploadAdapter


def add(path: str) -> str:
    s = load_settings()
    store = ObjectStore(s.s3_endpoint, s.s3_key, s.s3_secret, s.s3_bucket)
    store.ensure_bucket()
    reg = Registrar(make_engine(s.database_url), store)
    seen = new_content = new_locations = 0
    for item in UploadAdapter().scan(path):
        r = reg.register(item)
        seen += 1
        new_content += r.new_content
        new_locations += r.new_location
    return f"{seen} files, {new_content} new content, {new_locations} new locations"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lake")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("add", help="add a file or folder").add_argument("path")
    sub.add_parser("serve", help="run the MCP server on 127.0.0.1:8000")
    args = parser.parse_args(argv)
    if args.cmd == "add":
        print(add(args.path))
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("lake_server.app:build_app", factory=True, host="127.0.0.1", port=8000)
    return 0


if __name__ == "__main__":
    sys.exit(main())
