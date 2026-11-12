"""What an adapter yields, and the adapter protocol. Adapters only find and read items."""

from collections.abc import Iterator
from dataclasses import dataclass
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


class Adapter(Protocol):
    name: str

    def scan(self, root: str) -> Iterator[Item]: ...
