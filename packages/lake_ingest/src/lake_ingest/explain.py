"""explain_path: why was a path indexed, ignored, or labelled the way it was?"""

import json
from pathlib import Path

from lake_core.labels import effective_labels
from sqlalchemy import Engine, text

from lake_ingest.disk import DiskAdapter


def disk_roots(engine: Engine) -> list[str]:
    with engine.connect() as c:
        cfg = c.execute(text("select config from source where name='disk'")).scalar_one_or_none()
    return list((cfg or {}).get("roots", []))


def record_disk_root(engine: Engine, root: str) -> None:
    roots = sorted({*disk_roots(engine), root})
    with engine.begin() as c:
        c.execute(
            text(
                "insert into source(name,kind,config) values ('disk','disk',cast(:c as jsonb)) "
                "on conflict (name) do update set config = excluded.config"
            ),
            {"c": json.dumps({"roots": roots})},
        )


def explain_path_json(engine: Engine, path: str, default_rules: str = "") -> str:
    path = str(Path(path).resolve()) if not path.startswith(("http://", "https://")) else path
    out: dict[str, object] = {"path": path}
    with engine.connect() as c:
        row = c.execute(
            text(
                "select c.sha256, c.source_type from location l "
                "join content c on c.sha256=l.content_sha256 where l.path=:p limit 1"
            ),
            {"p": path},
        ).first()
        out["indexed"] = row is not None
        if row:
            out["content"] = {"sha256": row.sha256, "type": row.source_type}
            out["labels"] = effective_labels(c, row.sha256)
    roots = [r for r in disk_roots(engine) if path == r or path.startswith(r.rstrip("/") + "/")]
    if roots:
        root = max(roots, key=len)
        d = DiskAdapter(default_rules).decide(root, path)
        out["root"] = root
        out["ignore"] = {"ignored": d.ignored, "reason": d.reason}
    elif not row:
        out["note"] = "path is not under any known disk root and was never indexed"
    return json.dumps(out)
