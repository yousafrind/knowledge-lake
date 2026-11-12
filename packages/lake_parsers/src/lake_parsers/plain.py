"""Fallback parser for text-like files. Also the test double for the parse step."""

from lake_parsers.base import Parsed


class PlainTextParser:
    name = "plain"
    version = "1"

    def parse(self, data: bytes, filename: str) -> Parsed:
        text = data.decode("utf-8", errors="replace")
        return Parsed(markdown=text, structure={"sections": []})
