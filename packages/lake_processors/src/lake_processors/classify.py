"""classify: attach labels to a document. Precedence: manual > rule > folder > content."""

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import pathspec
import yaml
from sqlalchemy import text

from lake_processors.contract import Context

PRECEDENCE = ["manual", "rule", "folder", "content"]


@dataclass(frozen=True)
class Rule:
    path: str
    labels: dict[str, str]


def load_rules(yaml_text: str) -> list[Rule]:
    doc: dict[str, Any] = yaml.safe_load(yaml_text) or {}
    return [
        Rule(r["path"], {k: str(v) for k, v in r["labels"].items()}) for r in doc.get("rules", [])
    ]


class ClassifyProcessor:
    name = "classify"
    cost = "cpu"

    def __init__(self, rules: list[Rule]) -> None:
        self.rules = rules
        # rules are part of the processor identity: edit rules.yaml and the jobs run again
        digest = hashlib.sha256(repr([(r.path, sorted(r.labels.items())) for r in rules]).encode())
        self.version = "1-" + digest.hexdigest()[:8]

    def run(self, target: str, ctx: Context) -> None:
        sha = target.rsplit(":", 1)[0]
        with ctx.engine.begin() as c:
            stype = c.execute(
                text("select source_type from content where sha256=:h"), {"h": sha}
            ).scalar_one()
            paths = [
                r[0]
                for r in c.execute(
                    text("select path from location where content_sha256=:h"), {"h": sha}
                )
            ]
            found: list[tuple[str, str, str, float]] = [("type", stype, "content", 1.0)]
            for path in paths:
                folder = PurePosixPath(path).parent
                if folder.name:
                    found.append(("folder", folder.name, "folder", 0.5))
                for rule in self.rules:
                    if pathspec.PathSpec.from_lines("gitignore", [rule.path]).match_file(
                        path.lstrip("/")
                    ):
                        found += [(k, v, "rule", 1.0) for k, v in rule.labels.items()]
            for key, value, source, conf in found:
                c.execute(
                    text(
                        "insert into label(content_sha,key,value,source,confidence) "
                        "values (:h,:k,:v,:s,:c) on conflict (content_sha,key,source) "
                        "do update set value=excluded.value, confidence=excluded.confidence "
                        "where label.source <> 'manual'"
                    ),
                    {"h": sha, "k": key, "v": value, "s": source, "c": conf},
                )


def effective_labels(c: Any, sha: str) -> dict[str, str]:
    """Winning value per key by source precedence (manual first)."""
    rows = c.execute(text("select key, value, source from label where content_sha=:h"), {"h": sha})
    best: dict[str, tuple[int, str]] = {}
    for key, value, source in rows:
        rank = PRECEDENCE.index(source)
        if key not in best or rank < best[key][0]:
            best[key] = (rank, value)
    return {k: v for k, (_, v) in best.items()}
