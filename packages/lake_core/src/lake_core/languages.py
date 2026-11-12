"""Source-code languages by file suffix. Shared by ingest (typing) and lake_code (parsing)."""

from pathlib import PurePosixPath

SUFFIX_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}


def language_of(path: str) -> str | None:
    return SUFFIX_LANGUAGE.get(PurePosixPath(path).suffix.lower())
