"""The processor contract (see docs/adr/0001-processor-run-signature.md)."""

from dataclasses import dataclass
from typing import Protocol

from lake_core.objectstore import ObjectStore
from sqlalchemy import Engine


@dataclass(frozen=True)
class Context:
    engine: Engine
    store: ObjectStore


class Processor(Protocol):
    name: str
    version: str  # bump to trigger reprocessing
    cost: str  # "cpu", "gpu" or "llm"

    def run(self, target: str, ctx: Context) -> None: ...

    # Must be idempotent: running twice with the same version changes nothing.


class Registry:
    def __init__(self) -> None:
        self._by_name: dict[str, Processor] = {}

    def add(self, p: Processor) -> None:
        self._by_name[p.name] = p

    def get(self, name: str) -> Processor:
        return self._by_name[name]

    def names(self) -> list[str]:
        return list(self._by_name)
