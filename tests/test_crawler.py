import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from lake_ingest.crawl import CrawlAdapter

PAGES = {
    "/docs/index.html": '<title>Home</title><body><h2>Welcome</h2><a href="a.html">A</a> '
    '<a href="b.html#frag">B</a> <a href="/other/x.html">out of prefix</a>'
    '<a href="private.html">P</a></body>',
    "/docs/a.html": '<title>Page A</title><body><p>alpha</p><a href="index.html">home</a></body>',
    "/docs/b.html": "<title>Page B</title><body><p>beta</p></body>",
    "/docs/private.html": "<title>Private</title><body>secret</body>",
    "/other/x.html": "<title>X</title><body>x</body>",
    "/robots.txt": "User-agent: *\nDisallow: /docs/private.html\n",
}


class H(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = PAGES.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header(
            "content-type", "text/plain" if self.path.endswith(".txt") else "text/html"
        )
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *a: object) -> None:
        pass


@pytest.fixture
def base() -> Iterator[str]:
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_crawl_stays_in_prefix_obeys_robots_and_makes_markdown(base: str) -> None:
    items = list(CrawlAdapter(delay=0).scan(base + "/docs/index.html"))
    paths = sorted(i.path.removeprefix(base) for i in items)
    assert paths == ["/docs/a.html", "/docs/b.html", "/docs/index.html"]
    a = next(i for i in items if i.path.endswith("a.html"))
    assert a.markdown and a.markdown.startswith("# Page A") and "alpha" in a.markdown
    assert a.source_type == "html" and a.source == "crawl"


def test_page_limit(base: str) -> None:
    assert len(list(CrawlAdapter(max_pages=1, delay=0).scan(base + "/docs/index.html"))) == 1
