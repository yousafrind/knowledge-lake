"""What an adapter yields, and the adapter protocol. Adapters only find and read items."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Item:
    data: bytes
    path: str
    source: str  # source name, e.g. "upload"
    mtime: datetime | None = None
    source_type: str | None = None  # hint; detected from the suffix when None
    markdown: str | None = None  # set only when the adapter already has markdown
    tier: str = "original"  # "derived" for chats and generated documents
    title: str | None = None
    meta: dict[str, object] = field(default_factory=dict)  # merged into the manifest
    on_secrets: str = "quarantine"  # or "redact" (chats: never lose the conversation)


class Adapter(Protocol):
    name: str

    def scan(self, root: str) -> Iterator[Item]: ...
