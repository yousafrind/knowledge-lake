import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from conftest import ADMIN
from lake_cli.main import build_registry
from lake_cli.restore import backup, restore_drill
from lake_core.db import make_engine, upgrade_to_head
from lake_core.objectstore import ObjectStore
from lake_ingest.adapter import Item
from lake_ingest.registrar import Registrar
from lake_processors.contract import Context
from lake_processors.loop import run_until_idle
from sqlalchemy import text


@pytest.fixture
def scratch_url() -> Iterator[str]:
    name = f"lake_scratch_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(ADMIN, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    yield ADMIN.rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://") + f"/{name}"
    with psycopg.connect(ADMIN, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def test_drill_rebuilds_derived_data_from_packages(
    db_url: str, scratch_url: str, store: ObjectStore, tmp_path: Path
) -> None:
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    reg = Registrar(eng, store)
    a = "# A\n\nSee [b](/b.md). Replication copies data."
    b = "# B\n\nFailover promotes a standby."
    reg.register(Item(a.encode(), "/a.md", "upload", markdown=a))
    reg.register(Item(b.encode(), "/b.md", "upload", markdown=b))
    with eng.begin() as c:
        sha = c.execute(text("select content_sha256 from location where path='/a.md'")).scalar()
        c.execute(
            text(
                "insert into label(content_sha,key,value,source) values (:s,'project','x','manual')"
            ),
            {"s": sha},
        )
    registry = build_registry("hash")
    run_until_idle(Context(eng, store), registry)

    dump = backup(db_url, tmp_path / "lake.dump")
    report = restore_drill(dump, scratch_url, store, registry, compare_to=db_url)

    assert report["ok"], report
    assert report["scratch"]["chunk"] == report["source"]["chunk"] > 0
    assert report["scratch"]["embedding"] == report["source"]["embedding"] > 0
    with make_engine(scratch_url).connect() as c:
        manual = c.execute(text("select value from label where source='manual'")).scalar()
        # a new source must not collide with restored ids
        c.execute(text("select nextval(pg_get_serial_sequence('source','id'))")).scalar()
    assert manual == "x"
