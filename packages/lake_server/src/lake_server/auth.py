"""Bearer-token auth for stages B and C: tokens and their scopes live in config/tokens.toml.

`public_url` (top level) is the address clients see. Only the SHA-256 of a token is stored.
The MCP SDK does the OAuth resource-server side (401 + metadata); this module is the
`TokenVerifier` it asks. Scopes: read, code:read, write, admin, photos:read.
"""

import tomllib
from pathlib import Path
from typing import Any

from lake_core.tokens import hash_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl


class FileTokenVerifier:
    def __init__(self, path: Path) -> None:
        cfg = tomllib.loads(Path(path).read_text())
        self.by_hash = {t["sha256"]: (name, t["scopes"]) for name, t in cfg["tokens"].items()}

    async def verify_token(self, token: str) -> AccessToken | None:
        found = self.by_hash.get(hash_token(token))
        if found is None:
            return None
        name, scopes = found
        return AccessToken(token=token, client_id=name, scopes=list(scopes))


def per_minute(path: Path) -> int:
    return int(tomllib.loads(Path(path).read_text()).get("limits", {}).get("per_minute", 0))


def load_auth(path: Path) -> dict[str, Any]:
    """Keyword arguments for `create_server` that turn bearer auth on (needs `public_url`)."""
    base = tomllib.loads(Path(path).read_text())["public_url"].rstrip("/")
    return {
        "token_verifier": FileTokenVerifier(path),
        "auth": AuthSettings(
            issuer_url=AnyHttpUrl(base),
            resource_server_url=AnyHttpUrl(f"{base}/mcp"),
            validate_token_resource=False,
        ),
    }
