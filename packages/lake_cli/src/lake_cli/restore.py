"""Backup and restore drill.

A backup is one `pg_dump` (the object store is mirrored separately, see deploy/stage-b).
The drill proves the claim in the architecture: restore only the tables that cannot be
rebuilt, then regenerate everything else from the packages in the object store.
"""

import subprocess
from pathlib import Path
from typing import Any

from lake_core.db import make_engine, upgrade_to_head
from lake_core.jobs import enqueue_job
from lake_core.objectstore import ObjectStore
from lake_processors.contract import Context, Registry
from lake_processors.loop import run_until_idle
from sqlalchemy import text

# Parents first (foreign keys). Everything else is derived: chunk, embedding, edge, groups, jobs.
IRREPLACEABLE = ["source", "content", "location", "package", "quarantine", "label"]
SYNC_SEQ = "select setval(pg_get_serial_sequence('source','id'), max(id)) from source"
COUNTED = ["chunk", "embedding", "edge", "doc_group_member"]


def _pg(url: str) -> str:
    return url.replace("+psycopg", "")


def backup(db_url: str, out: Path) -> Path:
    subprocess.run(["pg_dump", "-Fc", "-f", str(out), _pg(db_url)], check=True)
    return out


def counts(db_url: str) -> dict[str, int]:
    with make_engine(db_url).connect() as c:
        return {t: c.execute(text(f"select count(*) from {t}")).scalar() or 0 for t in COUNTED}


def restore_drill(
    dump: Path,
    scratch_url: str,
    store: ObjectStore,
    registry: Registry,
    compare_to: str | None = None,
) -> dict[str, Any]:
    """Restore into an empty scratch database, rebuild derived data, compare with the original."""
    upgrade_to_head(scratch_url)
    for t in IRREPLACEABLE:  # one at a time, parents first: pg_dump does not order data by FKs
        subprocess.run(
            ["pg_restore", "--data-only", "-t", t, "-d", _pg(scratch_url), str(dump)], check=True
        )
    eng = make_engine(scratch_url)
    with eng.begin() as c:
        c.execute(text("delete from label where source <> 'manual'"))  # rules re-derive these
        c.execute(text(SYNC_SEQ))
        for (pid,) in c.execute(text("select id from package where canonical")).all():
            enqueue_job(c, "chunk", pid)
    run_until_idle(Context(eng, store), registry)
    report: dict[str, Any] = {"scratch": counts(scratch_url)}
    if compare_to:
        report["source"] = counts(compare_to)
        report["ok"] = report["scratch"] == report["source"]
    return report
