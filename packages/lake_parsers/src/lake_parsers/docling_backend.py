"""Docling backend (default for PDFs, Office files and images). Imported lazily: it is heavy."""

import tempfile
from importlib.metadata import version as _version
from pathlib import Path

from lake_parsers.base import Parsed


class DoclingParser:
    name = "docling"

    def __init__(self) -> None:
        self.version = _version("docling")
        self._converter = None

    def parse(self, data: bytes, filename: str) -> Parsed:
        if self._converter is None:
            from docling.document_converter import DocumentConverter  # type: ignore[import-not-found,unused-ignore]

            self._converter = DocumentConverter()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / Path(filename).name
            path.write_bytes(data)
            doc = self._converter.convert(path).document  # type: ignore[attr-defined]
        structure = doc.export_to_dict()
        return Parsed(markdown=doc.export_to_markdown(), structure={"docling": structure})
