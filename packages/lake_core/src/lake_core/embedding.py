"""Embedders. Shared by processors (documents) and retrieval (queries): same model both sides."""

import hashlib
import math
import re
from typing import Any, Protocol

DIM = 384  # matches embedding.vec in the schema


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Offline, deterministic bag-of-words hashing. Lexical overlap only, no semantics.

    For tests and for running with no model download. Not for real retrieval quality.
    """

    model = "hash-384"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * DIM
            for w in re.findall(r"\w+", t.lower()):
                h = int.from_bytes(hashlib.md5(w.encode()).digest()[:8], "big")
                v[h % DIM] += 1.0 if (h >> 63) == 0 else -1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class BgeSmallEmbedder:
    """BAAI/bge-small-en-v1.5 via sentence-transformers (384 dims). Needs the model download."""

    model = "bge-small-en-v1.5"

    def __init__(self) -> None:
        self._m: Any = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._m is None:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found,unused-ignore]

            self._m = SentenceTransformer("BAAI/bge-small-en-v1.5")
        vecs = self._m.encode(texts, normalize_embeddings=True)
        return [list(map(float, v)) for v in vecs]


def make_embedder(name: str) -> Embedder:
    if name == "hash":
        return HashEmbedder()
    if name == "bge-small":
        return BgeSmallEmbedder()
    raise ValueError(f"unknown embedder: {name}")


def to_pgvector(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"
