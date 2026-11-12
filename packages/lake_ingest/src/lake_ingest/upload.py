"""Upload adapter: walk a file or folder and yield items."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from lake_ingest.adapter import Item

TEXT_SUFFIXES = {".md", ".txt"}


class UploadAdapter:
    name = "upload"

    def scan(self, root: str) -> Iterator[Item]:
        base = Path(root).resolve()
        files = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file())
        for p in files:
            data = p.read_bytes()
            md = (
                data.decode("utf-8", errors="replace")
                if p.suffix.lower() in TEXT_SUFFIXES
                else None
            )
            mtime = datetime.fromtimestamp(p.stat().st_mtime, UTC)
            yield Item(data, str(p), self.name, mtime, markdown=md)
