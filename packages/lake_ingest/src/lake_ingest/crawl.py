"""Website crawler adapter: same-site, depth- and page-limited, robots.txt aware."""

import time
from collections import deque
from collections.abc import Iterator
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

from lake_ingest.adapter import Item

USER_AGENT = "knowledge-lake-crawler/0.1"


class CrawlAdapter:
    name = "crawl"

    def __init__(
        self, max_pages: int = 100, max_depth: int = 3, delay: float = 0.5, same_prefix: bool = True
    ) -> None:
        self.max_pages, self.max_depth, self.delay, self.same_prefix = (
            max_pages,
            max_depth,
            delay,
            same_prefix,
        )

    def scan(self, root: str) -> Iterator[Item]:
        start = urldefrag(root)[0]
        parts = urlparse(start)
        origin = f"{parts.scheme}://{parts.netloc}"
        prefix = start.rsplit("/", 1)[0] + "/" if self.same_prefix else origin + "/"
        robots = RobotFileParser()
        with httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True
        ) as http:
            try:
                robots.parse(http.get(origin + "/robots.txt").text.splitlines())
            except httpx.HTTPError:
                robots.parse([])
            seen, queue, pages = {start}, deque([(start, 0)]), 0
            while queue and pages < self.max_pages:
                url, depth = queue.popleft()
                if not robots.can_fetch(USER_AGENT, url):
                    continue
                try:
                    resp = http.get(url)
                except httpx.HTTPError:
                    continue
                if resp.status_code != 200 or "html" not in resp.headers.get("content-type", ""):
                    continue
                pages += 1
                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer"]):
                    tag.decompose()
                md = markdownify(str(soup.body or soup), heading_style="ATX").strip()
                title = soup.title.string.strip() if soup.title and soup.title.string else ""
                if title and not md.lstrip().startswith("# "):
                    md = f"# {title}\n\n{md}"
                yield Item(resp.content, str(resp.url), self.name, source_type="html", markdown=md)
                if depth < self.max_depth:
                    for a in soup.find_all("a", href=True):
                        link = urldefrag(urljoin(url, str(a["href"])))[0]
                        if link.startswith(prefix) and link not in seen:
                            seen.add(link)
                            queue.append((link, depth + 1))
                time.sleep(self.delay)
