"""API tokens: random, shown once, stored only as a SHA-256 hash."""

import hashlib
import secrets


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    """A fresh random token and the hash to store for it."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)
