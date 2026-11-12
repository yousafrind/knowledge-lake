"""Type detection: trust the content over the extension when they disagree about binaries."""

from functools import lru_cache
from pathlib import PurePosixPath
from typing import Any

from lake_core.languages import language_of

SUFFIX_TYPES = {
    ".pdf": "pdf",
    ".md": "markdown",
    ".txt": "text",
    ".html": "html",
    ".htm": "html",
    ".docx": "docx",
    ".epub": "epub",
    ".json": "json",
}
# Magika labels we map to our types. Anything else becomes "binary" (or "code" for source files).
MAGIKA_TYPES = {
    "pdf": "pdf",
    "docx": "docx",
    "epub": "epub",
    "html": "html",
    "markdown": "markdown",
    "txt": "text",
    "json": "json",
    "jpeg": "image",
    "png": "image",
    "gif": "image",
    "webp": "image",
    "mp3": "audio",
    "wav": "audio",
    "mp4": "video",
}
CODE_LABELS = {"python", "javascript", "typescript", "java", "c", "cpp", "go", "rust", "shell"}
MAGIC = {b"%PDF-": "pdf", b"\x89PNG": "image", b"\xff\xd8\xff": "image", b"GIF8": "image"}
BINARY_MAGIC = (*MAGIC, b"PK\x03\x04")
BINARY_TYPES = {"pdf", "docx", "epub", "image", "audio", "video"}


@lru_cache(maxsize=1)
def _magika() -> Any:
    from magika import Magika

    return Magika()


def sniff(data: bytes) -> str:
    label = _magika().identify_bytes(data[:1_000_000]).output.label
    if label in MAGIKA_TYPES:
        return MAGIKA_TYPES[label]
    return "code" if label in CODE_LABELS else "binary"


def detect_type(data: bytes, path: str) -> str:
    for magic, kind in MAGIC.items():
        if data.startswith(magic):
            return kind  # unambiguous signatures win over any extension
    if language_of(path) and b"\x00" not in data[:4096]:
        return "code"
    by_suffix = SUFFIX_TYPES.get(PurePosixPath(path).suffix.lower())
    if (
        by_suffix is not None
        and by_suffix not in BINARY_TYPES
        and not data.startswith(BINARY_MAGIC)
        and b"\x00" not in data[:4096]
    ):
        return by_suffix  # cheap and trusted for plain text formats
    sniffed = sniff(data)
    if by_suffix is None:
        return sniffed
    return sniffed if sniffed in BINARY_TYPES else by_suffix  # a .pdf that is not a PDF stays pdf
