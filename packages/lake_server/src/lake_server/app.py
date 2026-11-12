"""ASGI app: `uvicorn lake_server.app:app` (settings come from LAKE_* variables)."""

from lake_core.db import make_engine
from lake_core.embedding import make_embedder
from lake_core.settings import load_settings

from lake_server.mcp_tools import create_server


def build_app():  # type: ignore[no-untyped-def]
    s = load_settings()
    return create_server(
        make_engine(s.database_url), make_embedder(s.embedder)
    ).streamable_http_app()
