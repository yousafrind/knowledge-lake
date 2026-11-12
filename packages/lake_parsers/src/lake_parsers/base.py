"""One parser interface; backends (Docling, MinerU, ...) sit behind it."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Parsed:
    markdown: str
    structure: dict[str, Any] = field(default_factory=dict)
    assets: dict[str, bytes] = field(default_factory=dict)  # filename -> bytes
    qa: dict[str, Any] = field(default_factory=dict)  # filled by QA scoring (W-018)


class Parser(Protocol):
    name: str
    version: str

    def parse(self, data: bytes, filename: str) -> Parsed: ...
