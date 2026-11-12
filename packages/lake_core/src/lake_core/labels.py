"""Label precedence, shared by processors, ingest and the server."""

from typing import Any

from sqlalchemy import text

PRECEDENCE = ["manual", "rule", "folder", "content"]


def effective_labels(c: Any, sha: str) -> dict[str, str]:
    """Winning value per key by source precedence (manual first)."""
    rows = c.execute(text("select key, value, source from label where content_sha=:h"), {"h": sha})
    best: dict[str, tuple[int, str]] = {}
    for key, value, source in rows:
        rank = PRECEDENCE.index(source)
        if key not in best or rank < best[key][0]:
            best[key] = (rank, value)
    return {k: v for k, (_, v) in best.items()}
