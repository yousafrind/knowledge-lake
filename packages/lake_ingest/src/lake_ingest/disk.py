"""Disk walker: read-only walk of a folder tree with layered ignore rules.

Rule layers, all gitignore syntax: built-in defaults, <root>/.lakeignore, and any .gitignore
found in the tree (applies below its own folder). `decide()` explains why a path is skipped.
"""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pathspec

from lake_ingest.adapter import Item

TEXT_SUFFIXES = {".md", ".txt"}
DEFAULT_MAX_BYTES = 200 * 1024 * 1024


@dataclass(frozen=True)
class Decision:
    ignored: bool
    reason: str  # e.g. "default rules: node_modules/" or "indexed"


@lru_cache(maxsize=256)
def _spec_cached(lines: tuple[str, ...]) -> "pathspec.PathSpec[Any]":
    return pathspec.PathSpec.from_lines("gitignore", lines)


def _spec(lines: list[str]) -> "pathspec.PathSpec[Any]":
    return _spec_cached(tuple(lines))


def _matching_line(lines: list[str], rel: str) -> str | None:
    for line in reversed(lines):
        if line.strip() and not line.startswith("#") and _spec([line]).match_file(rel):
            return line.strip()
    return None


class DiskAdapter:
    name = "disk"

    def __init__(self, default_rules: str = "", max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.default_lines = default_rules.splitlines()
        self.max_bytes = max_bytes
        self.skipped: list[tuple[str, str]] = []

    def _layers(self, root: Path, directory: Path) -> list[tuple[str, Path, list[str]]]:
        """Rule layers in force inside `directory`: defaults, root .lakeignore, .gitignore chain."""
        layers = [("default rules", root, self.default_lines)]
        chain = [root]
        for part in directory.relative_to(root).parts:
            chain.append(chain[-1] / part)
        for d in chain:
            for fname in (".lakeignore", ".gitignore"):
                if fname == ".lakeignore" and d != root:
                    continue
                f = d / fname
                if f.is_file():
                    layers.append(
                        (f"{fname} in {d}", d, f.read_text(errors="replace").splitlines())
                    )
        return layers

    def _why(self, root: Path, p: Path, is_dir: bool) -> str | None:
        verdict = None
        for label, base, lines in self._layers(root, p.parent):
            rel = p.relative_to(base).as_posix() + ("/" if is_dir else "")
            if _spec(lines).match_file(rel):
                verdict = f"{label}: {_matching_line(lines, rel)}"
        return verdict

    def decide(self, root: str | Path, path: str | Path) -> Decision:
        """Why would this path be indexed or skipped? (Used by explain_path.)"""
        root, path = Path(root).resolve(), Path(path).resolve()
        chain = [root]
        for part in path.relative_to(root).parts:
            chain.append(chain[-1] / part)
        for p in chain[1:]:
            why = self._why(root, p, p.is_dir())
            if why:
                return Decision(True, why)
        return Decision(False, "indexed")

    def scan(self, root: str) -> Iterator[Item]:
        base = Path(root).resolve()
        self.skipped = []
        yield from self._walk(base, base)

    def _walk(self, root: Path, directory: Path) -> Iterator[Item]:
        for entry in sorted(os.scandir(directory), key=lambda e: e.name):
            p = Path(entry.path)
            if entry.is_symlink():
                self.skipped.append((str(p), "symlink"))
                continue
            if entry.is_dir(follow_symlinks=False):
                why = self._why(root, p, True)
                if why:
                    self.skipped.append((str(p) + "/", why))
                else:
                    yield from self._walk(root, p)
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            why = self._why(root, p, False)
            if why is None:
                size = entry.stat().st_size
                if size == 0:
                    why = "empty file"
                elif size > self.max_bytes:
                    why = f"larger than {self.max_bytes} bytes"
            if why:
                self.skipped.append((str(p), why))
                continue
            data = p.read_bytes()
            md = (
                data.decode("utf-8", errors="replace")
                if p.suffix.lower() in TEXT_SUFFIXES
                else None
            )
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, UTC)
            yield Item(data, str(p), self.name, mtime, markdown=md)
