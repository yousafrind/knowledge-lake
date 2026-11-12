"""Write-back tools (scope `write`): agents save conversations and generated documents."""

import json
import re
from datetime import UTC, datetime

from lake_ingest.adapter import Item
from lake_ingest.chat import render_conversation
from lake_ingest.registrar import Registrar
from sqlalchemy import Engine, text

MAX_CHARS = 500_000


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "untitled"


def _labels(engine: Engine, sha: str, tags: list[str] | None, project: str | None) -> None:
    pairs = [(f"tag:{t.strip()}", "1") for t in tags or [] if t.strip()]
    if project:
        pairs.append(("project", project.strip()))
    with engine.begin() as c:
        for key, value in pairs:
            c.execute(
                text(
                    "insert into label(content_sha,key,value,source) values (:h,:k,:v,'manual') "
                    "on conflict (content_sha,key,source) do update set value=excluded.value"
                ),
                {"h": sha, "k": key, "v": value},
            )


def _save(
    engine: Engine,
    reg: Registrar,
    kind: str,
    title: str,
    body: str,
    tags: list[str] | None,
    project: str | None,
    meta: dict[str, object],
) -> str:
    if not title.strip() or not body.strip():
        raise ValueError("title and content are required")
    if len(body) > MAX_CHARS:
        raise ValueError(f"content is over {MAX_CHARS} characters")
    now = datetime.now(UTC)
    item = Item(
        body.encode(),
        f"{kind}://{_slug(title)}-{now:%Y%m%d%H%M%S}",
        kind,
        now,
        source_type=kind,
        markdown=body,
        tier="derived",
        title=title.strip(),
        meta={"trust": "derived", "saved_by": "mcp", **meta},
        on_secrets="redact",
    )
    r = reg.register(item)
    _labels(engine, r.content_sha256, tags, project)
    return json.dumps(
        {
            "id": f"lake://{r.content_sha256}#1",
            "status": "saved" if r.new_content else "duplicate",
            "redacted": list(r.redactions),
            "note": "searchable after the next `lake work` run",
        }
    )


def save_document_json(
    engine: Engine,
    reg: Registrar,
    title: str,
    content: str,
    tags: list[str] | None = None,
    project: str | None = None,
) -> str:
    return _save(engine, reg, "generated", title, content, tags, project, {})


def save_conversation_json(
    engine: Engine,
    reg: Registrar,
    title: str,
    messages: list[dict[str, str]],
    tags: list[str] | None = None,
    project: str | None = None,
) -> str:
    if not messages:
        raise ValueError("messages must not be empty")
    body = render_conversation(title, messages)
    return _save(engine, reg, "chat", title, body, tags, project, {"origin": "mcp"})
