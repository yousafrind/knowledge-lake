"""ID rules from the architecture's identity table. Same input, same ID."""

import hashlib


def content_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _h(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def location_id(source: str, path: str, content_hash: str) -> str:
    """A new hash at the same path is a new location row."""
    return _h("location", source, path, content_hash)[:32]


def package_id(content_hash: str, rev: int) -> str:
    return f"{content_hash}:{rev}"


def chunk_id(pkg_id: str, ordinal: int, chunker_version: str) -> str:
    return _h("chunk", pkg_id, str(ordinal), chunker_version)[:32]


def job_id(processor: str, version: str, target: str) -> str:
    """A retry reuses the row, so the ID has no attempt number in it."""
    return _h("job", processor, version, target)[:32]
