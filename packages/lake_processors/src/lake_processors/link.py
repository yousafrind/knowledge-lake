"""link: find links in a package and resolve them to other documents we hold."""

import posixpath
import re
from urllib.parse import unquote, urldefrag, urljoin

from lake_core.objectstore import package_prefix
from sqlalchemy import text

from lake_processors.contract import Context

MD_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def resolve_ref(base: str, href: str) -> str | None:
    """Turn a link found in a document at `base` into an absolute path or URL."""
    href = unquote(urldefrag(href)[0])
    if not href or href.startswith(("mailto:", "tel:", "javascript:")):
        return None
    if base.startswith(("http://", "https://")):
        return urljoin(base, href)
    if href.startswith(("http://", "https://")):
        return href
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), href))


class LinkProcessor:
    name = "link"
    version = "1"
    cost = "cpu"

    def run(self, target: str, ctx: Context) -> None:
        sha, rev = target.rsplit(":", 1)
        md = ctx.store.get(package_prefix(sha, int(rev)) + "content.md").decode()
        with ctx.engine.begin() as c:
            base = c.execute(
                text("select path from location where content_sha256=:h order by seen_at limit 1"),
                {"h": sha},
            ).scalar_one_or_none()
            if base:
                for anchor, href in MD_LINK.findall(md):
                    ref = resolve_ref(base, href)
                    if ref:
                        c.execute(
                            text(
                                "insert into edge(src_sha,dst_ref,anchor) values (:s,:r,:a) "
                                "on conflict do nothing"
                            ),
                            {"s": sha, "r": ref, "a": anchor or None},
                        )
            # resolve every still-open edge: targets may have arrived after the link was seen
            c.execute(
                text(
                    "update edge set dst_sha = l.content_sha256 from location l "
                    "where edge.dst_sha is null and l.path = edge.dst_ref"
                )
            )
