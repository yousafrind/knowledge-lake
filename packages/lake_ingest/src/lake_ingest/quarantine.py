"""Helpers for the quarantine list (held files that contained secrets)."""

from typing import Any

from sqlalchemy import Engine, text


def held(engine: Engine) -> list[Any]:
    with engine.connect() as c:
        return list(
            c.execute(
                text(
                    "select q.content_sha as sha, q.reasons, "
                    "(select path from location where content_sha256=q.content_sha limit 1) "
                    "as path "
                    "from quarantine q where q.status='held' order by q.created_at"
                )
            ).all()
        )
