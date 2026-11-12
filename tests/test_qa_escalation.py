import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from lake_core.db import make_engine, upgrade_to_head
from lake_core.objectstore import ObjectStore, read_package
from lake_ingest.adapter import Item
from lake_ingest.registrar import Registrar
from lake_parsers.base import Parsed
from lake_parsers.plain import PlainTextParser
from lake_parsers.qa import score
from lake_parsers.remote import RemoteParser
from lake_processors.contract import Context, Registry
from lake_processors.loop import run_until_idle
from lake_processors.parse import ParseProcessor
from sqlalchemy import text


def test_qa_flags_empty_garbled_and_sparse_output() -> None:
    assert score(Parsed("good text " * 50), 2000, "pdf")["ok"]
    assert score(Parsed("   "), 2000, "pdf")["reasons"] == ["empty"]
    assert "garbled characters" in score(Parsed("a�" * 100), 500, "pdf")["reasons"]
    assert "too little text" in score(Parsed("tiny"), 5_000_000, "pdf")["reasons"][0]
    assert score(Parsed("tiny"), 5_000_000, "markdown")["ok"]  # sparse check is for binary types


class Weak(PlainTextParser):
    name = "weak"

    def parse(self, data: bytes, filename: str) -> Parsed:
        return Parsed("")


class Strong(PlainTextParser):
    name = "strong"

    def parse(self, data: bytes, filename: str) -> Parsed:
        return Parsed("# Recovered\n\nreal text")


class Boom(PlainTextParser):
    name = "boom"

    def parse(self, data: bytes, filename: str) -> Parsed:
        raise RuntimeError("gpu down")


def run_parse(db_url: str, store: ObjectStore, processor: ParseProcessor) -> dict:  # type: ignore[type-arg]
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    r = Registrar(eng, store).register(Item(b"%PDF scan", "/scan.pdf", "upload"))
    reg = Registry()
    reg.add(processor)
    run_until_idle(Context(eng, store), reg)
    with eng.connect() as c:
        assert c.execute(text("select count(*) from package")).scalar_one() == 1
    manifest, _ = read_package(store, r.content_sha256, 1)
    return manifest


def test_failed_qa_escalates_to_stronger_parser(db_url: str, store: ObjectStore) -> None:
    m = run_parse(db_url, store, ParseProcessor({}, Weak(), Strong()))
    assert m["parser"]["name"] == "strong" and m["qa"]["escalated_to"] == "strong"
    assert m["qa"]["first_failure"] == ["empty"] and not m["qa"]["needs_review"]


def test_escalation_failure_keeps_first_result_flagged(db_url: str, store: ObjectStore) -> None:
    m = run_parse(db_url, store, ParseProcessor({}, Weak(), Boom()))
    assert m["parser"]["name"] == "weak" and m["qa"]["needs_review"]
    assert "gpu down" in m["qa"]["escalation_error"]


@pytest.fixture
def gpu() -> Iterator[str]:
    class H(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["content-length"]))
            assert self.headers.get("authorization") == "Bearer t0k"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"markdown": "# From GPU"}).encode())

        def log_message(self, *a: object) -> None:
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_remote_parser_posts_file_and_reads_markdown(gpu: str) -> None:
    out = RemoteParser(gpu, token="t0k").parse(b"x", "a.pdf")
    assert out.markdown == "# From GPU"
