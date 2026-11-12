# 0003: Static bearer tokens before a full OAuth server

Status: accepted (W-032)

## Context
The architecture says the MCP server speaks Streamable HTTP "with OAuth" in stage C. A full
authorization server (client registration, authorize and token endpoints, consent) is a large,
security-critical build, and there is no cloud client here to test it against.

## Decision
Ship the resource-server half now: per-token scopes, a pluggable `TokenVerifier`
(`lake_server/auth.py`, tokens in `config/tokens.toml`, hashes only), 401 responses with the
SDK's OAuth metadata, rate limits and the edge allowlist. Tokens are issued by `lake token`.
The authorization server is deferred. When it is needed, either run an existing one (an
identity provider) and replace `FileTokenVerifier` with a verifier for its tokens, or implement
the SDK's `OAuthAuthorizationServerProvider`.

## Consequences
Claude Code, Codex and any client that accepts a configured bearer token work. claude.ai and
ChatGPT web connectors, which need OAuth, do not until the follow-up lands. The architecture
doc's tools table is unchanged; its OAuth line is updated to say tokens first.
