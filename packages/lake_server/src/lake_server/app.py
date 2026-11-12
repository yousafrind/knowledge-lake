"""ASGI app: `uvicorn lake_server.app:build_app --factory` (settings from LAKE_* variables).

MCP lives at /mcp. The web GUI is mounted only when LAKE_GUI_PASSWORD is set.
"""

from lake_core.db import make_engine
from lake_core.embedding import make_embedder
from lake_core.objectstore import ObjectStore
from lake_core.settings import load_settings
from starlette.applications import Starlette
from starlette.routing import Mount

from lake_server.gui import build_gui_routes
from lake_server.mcp_tools import create_server


def build_app() -> Starlette:
    s = load_settings()
    engine = make_engine(s.database_url)
    embedder = make_embedder(s.embedder)
    mcp_app = create_server(engine, embedder).streamable_http_app()
    routes: list = []  # type: ignore[type-arg]
    middleware: list = []  # type: ignore[type-arg]
    if s.gui_password:
        store = ObjectStore(s.s3_endpoint, s.s3_key, s.s3_secret, s.s3_bucket)
        routes, middleware = build_gui_routes(engine, embedder, store, s.gui_password)
    routes.append(Mount("/", app=mcp_app))
    return Starlette(routes=routes, middleware=middleware, lifespan=mcp_app.router.lifespan_context)
