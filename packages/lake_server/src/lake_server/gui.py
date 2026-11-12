"""Web GUI v1 (read-only): browse, search, reader. Server-rendered, single-user login."""

import hashlib
import hmac
import re
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from lake_core.embedding import Embedder
from lake_core.labels import effective_labels
from lake_core.objectstore import ObjectStore, package_prefix
from lake_core.titles import title_from_markdown
from lake_ingest.adapter import Item
from lake_ingest.crawl import CrawlAdapter
from lake_ingest.disk import DiskAdapter
from lake_ingest.registrar import Registrar
from lake_retrieval.search import search, slug
from markdown_it import MarkdownIt
from sqlalchemy import Engine, text
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from lake_server.admin import decide_group, jobs_overview, retry_job, review_items
from lake_server.edit import current_markdown, save_revision, set_manual_label

Handler = Callable[[Request], Awaitable[Response]]
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
md = MarkdownIt("commonmark", {"html": False})  # raw HTML in documents is escaped
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$", re.M)


def render_markdown(source: str) -> tuple[str, list[dict[str, Any]]]:
    """Render with heading ids that match the citation section slugs."""
    outline: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    tokens = md.parse(source)
    for i, t in enumerate(tokens):
        if t.type == "heading_open":
            level = int(t.tag[1])
            title = tokens[i + 1].content
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            anchor = slug(" > ".join(x for _, x in stack))
            t.attrSet("id", anchor)
            outline.append({"level": level, "text": title, "anchor": anchor})
    return md.renderer.render(tokens, md.options, {}), outline


def build_gui_routes(
    engine: Engine,
    embedder: Embedder,
    store: ObjectStore,
    password: str,
    config_dir: Path = Path("config"),
) -> tuple[list[Route], list[Middleware]]:
    secret = hashlib.sha256(f"lake-session:{password}".encode()).hexdigest()

    def authed(request: Request) -> bool:
        return bool(request.session.get("ok"))

    def guard(handler: Handler) -> Handler:
        async def wrapped(request: Request) -> Response:
            if not authed(request):
                return RedirectResponse("/login", status_code=303)
            return await handler(request)

        return wrapped

    async def login(request: Request) -> Response:
        if request.method == "POST":
            form = await request.form()
            given = str(form.get("password", ""))
            if hmac.compare_digest(given.encode(), password.encode()):
                request.session["ok"] = True
                return RedirectResponse("/", status_code=303)
            return templates.TemplateResponse(
                request, "login.html", {"error": "Wrong password."}, status_code=401
            )
        return templates.TemplateResponse(request, "login.html", {"error": None})

    async def logout(request: Request) -> Response:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    async def browse(request: Request) -> Response:
        prefix = request.query_params.get("path", "")
        with engine.connect() as c:
            rows = c.execute(
                text(
                    "select l.path, c.sha256, c.source_type, p.manifest->>'title' as title "
                    "from location l join content c on c.sha256=l.content_sha256 "
                    "left join package p on p.content_sha256=c.sha256 and p.canonical "
                    "order by l.path"
                )
            ).all()
        dirs: dict[str, int] = {}
        files = []
        base = prefix.rstrip("/") + "/" if prefix else "/"
        for r in rows:
            if not r.path.startswith(base):
                continue
            rest = r.path[len(base) :]
            if "/" in rest:
                name = rest.split("/", 1)[0]
                dirs[name] = dirs.get(name, 0) + 1
            else:
                files.append(
                    {
                        "name": rest,
                        "sha": r.sha256,
                        "source_type": r.source_type,
                        "title": r.title or rest,
                    }
                )
        parent = prefix.rstrip("/").rsplit("/", 1)[0] if prefix.count("/") > 1 else ""
        return templates.TemplateResponse(
            request,
            "browse.html",
            {
                "prefix": prefix,
                "parent": parent,
                "files": files,
                "dirs": [
                    {"name": n, "path": base + n, "count": k} for n, k in sorted(dirs.items())
                ],
            },
        )

    async def search_page(request: Request) -> Response:
        q = request.query_params.get("q", "").strip()
        hits = []
        for h in search(engine, embedder, q) if q else []:
            uri = h.citation["uri"]
            sha = uri[len("lake://") : len("lake://") + 64]
            hits.append(
                {
                    "sha": sha,
                    "anchor": uri.rsplit("/", 1)[-1],
                    "text": h.text,
                    "citation": h.citation,
                }
            )
        return templates.TemplateResponse(request, "search.html", {"q": q, "hits": hits})

    async def doc(request: Request) -> Response:
        sha = request.path_params["sha"]
        with engine.connect() as c:
            versions = c.execute(
                text(
                    "select rev, canonical, tier, manifest->>'title' as title from package "
                    "where content_sha256=:h order by rev desc"
                ),
                {"h": sha},
            ).all()
            locations = [
                r[0]
                for r in c.execute(
                    text("select path from location where content_sha256=:h order by path"),
                    {"h": sha},
                )
            ]
            links_out = c.execute(
                text("select dst_ref, dst_sha, anchor from edge where src_sha=:h order by dst_ref"),
                {"h": sha},
            ).all()
            links_in = c.execute(
                text(
                    "select e.src_sha, coalesce(p.manifest->>'title', e.src_sha) as title "
                    "from edge e left join package p on p.content_sha256=e.src_sha and p.canonical "
                    "where e.dst_sha=:h"
                ),
                {"h": sha},
            ).all()
            labels = effective_labels(c, sha)
        if not versions:
            return HTMLResponse("Not found (it may still be processing).", status_code=404)
        cur = next((v for v in versions if v.canonical), versions[0])
        source = store.get(package_prefix(sha, cur.rev) + "content.md").decode()
        body, outline = render_markdown(source)
        return templates.TemplateResponse(
            request,
            "doc.html",
            {
                "title": cur.title,
                "body": body,
                "outline": outline,
                "versions": versions,
                "sha": sha,
                "labels": labels,
                "locations": locations,
                "links_out": links_out,
                "links_in": links_in,
                "uri": f"lake://{sha}#{cur.rev}",
            },
        )

    async def review(request: Request) -> Response:
        return templates.TemplateResponse(request, "review.html", review_items(engine))

    async def group_decision(request: Request) -> Response:
        gid = int(request.path_params["gid"])
        decide_group(engine, gid, request.path_params["verb"] == "accept")
        return RedirectResponse("/review", status_code=303)

    async def quarantine_decision(request: Request) -> Response:
        if request.path_params["verb"] == "release":
            Registrar(engine, store).release(request.path_params["sha"])
        return RedirectResponse("/review", status_code=303)

    async def jobs(request: Request) -> Response:
        return templates.TemplateResponse(
            request, "jobs.html", {**jobs_overview(engine), "flash": request.query_params.get("m")}
        )

    async def job_retry(request: Request) -> Response:
        retry_job(engine, request.path_params["jid"])
        return RedirectResponse("/jobs", status_code=303)

    async def add_path(request: Request) -> Response:
        form = await request.form()
        path = str(form.get("path", "")).strip()
        if not Path(path).exists():
            return RedirectResponse("/jobs?m=Path+not+found+on+the+server", status_code=303)
        reg = Registrar(engine, store)
        rules = Path(config_dir) / "lakeignore.default"
        disk = DiskAdapter(rules.read_text() if rules.is_file() else "")
        n = sum(1 for item in disk.scan(path) if reg.register(item) is not None)
        return RedirectResponse(f"/jobs?m=Added+{n}+files", status_code=303)

    async def crawl(request: Request) -> Response:
        form = await request.form()
        url = str(form.get("url", "")).strip()
        if not url.startswith(("http://", "https://")):
            return RedirectResponse("/jobs?m=Enter+an+http(s)+URL", status_code=303)

        def work() -> None:
            reg = Registrar(engine, store)
            for item in CrawlAdapter().scan(url):
                reg.register(item)

        threading.Thread(target=work, daemon=True).start()
        return RedirectResponse("/jobs?m=Crawl+started", status_code=303)

    async def edit_page(request: Request) -> Response:
        sha = request.path_params["sha"]
        try:
            source = current_markdown(engine, store, sha)
        except ValueError:
            return HTMLResponse("Not found", status_code=404)
        return templates.TemplateResponse(
            request,
            "edit.html",
            {"sha": sha, "source": source, "preview": render_markdown(source)[0]},
        )

    async def edit_save(request: Request) -> Response:
        sha = request.path_params["sha"]
        form = await request.form()
        save_revision(engine, store, sha, str(form.get("markdown", "")))
        return RedirectResponse(f"/doc/{sha}", status_code=303)

    async def preview(request: Request) -> Response:
        form = await request.form()
        return HTMLResponse(render_markdown(str(form.get("markdown", "")))[0])

    async def new_page(request: Request) -> Response:
        if request.method == "POST":
            form = await request.form()
            body = str(form.get("markdown", ""))
            title = title_from_markdown(body, "untitled")
            path = f"gui://notes/{slug(title) or 'untitled'}.md"
            r = Registrar(engine, store).register(Item(body.encode(), path, "gui", markdown=body))
            return RedirectResponse(f"/doc/{r.content_sha256}", status_code=303)
        return templates.TemplateResponse(request, "new.html", {})

    async def label(request: Request) -> Response:
        form = await request.form()
        key, value = str(form.get("key", "")), str(form.get("value", ""))
        if key.strip() and value.strip():
            set_manual_label(engine, request.path_params["sha"], key, value)
        return RedirectResponse(f"/doc/{request.path_params['sha']}", status_code=303)

    routes = [
        Route("/login", login, methods=["GET", "POST"]),
        Route("/logout", logout, methods=["POST"]),
        Route("/", guard(browse)),
        Route("/search", guard(search_page)),
        Route("/doc/{sha}", guard(doc)),
        Route("/doc/{sha}/edit", guard(edit_page)),
        Route("/doc/{sha}/edit", guard(edit_save), methods=["POST"]),
        Route("/doc/{sha}/label", guard(label), methods=["POST"]),
        Route("/new", guard(new_page), methods=["GET", "POST"]),
        Route("/preview", guard(preview), methods=["POST"]),
        Route("/review", guard(review)),
        Route("/review/group/{gid:int}/{verb}", guard(group_decision), methods=["POST"]),
        Route("/quarantine/{sha}/{verb}", guard(quarantine_decision), methods=["POST"]),
        Route("/jobs", guard(jobs)),
        Route("/jobs/{jid}/retry", guard(job_retry), methods=["POST"]),
        Route("/sources/path", guard(add_path), methods=["POST"]),
        Route("/sources/crawl", guard(crawl), methods=["POST"]),
    ]
    return routes, [Middleware(SessionMiddleware, secret_key=secret, https_only=False)]
