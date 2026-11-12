# Stage C: public MCP endpoint

Stage B plus one public HTTPS path. The API already enforces scopes and rate limits when
`config/tokens.toml` exists (`lake token NAME read code:read` prints an entry; keep
`public_url` and `[limits] per_minute` at the top of the file). The edge adds the allowlist.

1. Put `Caddyfile` in front of the API container (set your hostname). Only `/mcp` and the
   OAuth metadata path pass, and only from the allowlisted ranges. The GUI, `explain_path`
   (admin scope) and the CLI are not reachable through it.
2. Give each cloud client its own token with the least scope it needs (`read` for search,
   `code:read` for code tools, never `admin`).
3. Postgres and MinIO stay on private interfaces.

## Not done

- **OAuth authorization server.** The API is an OAuth *resource server* (401 plus metadata, bearer
  tokens checked per request), but tokens are issued by hand with `lake token`. claude.ai's
  connector expects OAuth with dynamic client registration, so it cannot connect yet. See
  `docs/adr/0003-static-tokens-before-oauth.md`.
- **Caddy, DNS, TLS and the IP ranges** are untested here (no Docker, no network).
- Rate limits are per process (`lake_server/ratelimit.py`).
