"""JSON Schema validation for manifests and jobs."""

import json
from pathlib import Path
from typing import Any

import jsonschema

# ponytail: schemas live in repo-root schemas/ (per architecture); found relative to this
# file, so lake_core must run from a checkout. Package them if it is ever installed elsewhere.
SCHEMAS = Path(__file__).resolve().parents[4] / "schemas"


def _validate(name: str, doc: dict[str, Any]) -> None:
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text())
    jsonschema.validate(doc, schema)


def validate_manifest(doc: dict[str, Any]) -> None:
    _validate("manifest", doc)


def validate_job(doc: dict[str, Any]) -> None:
    _validate("job", doc)
