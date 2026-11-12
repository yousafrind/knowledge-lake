import pytest
from jsonschema import ValidationError
from lake_core import ids
from lake_core.db import make_engine, upgrade_to_head
from lake_core.schemas import validate_job, validate_manifest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

H = "a" * 64


@pytest.fixture
def conn(db_url: str):  # type: ignore[no-untyped-def]
    upgrade_to_head(db_url)
    with make_engine(db_url).connect() as c:
        yield c


def test_one_content_row_per_hash(conn: Connection) -> None:
    q = text("insert into content(sha256,size,source_type) values (:h,1,'pdf')")
    conn.execute(q, {"h": H})
    with pytest.raises(IntegrityError):
        conn.execute(q, {"h": H})


def test_one_canonical_package_per_content(conn: Connection) -> None:
    conn.execute(text("insert into content(sha256,size,source_type) values (:h,1,'pdf')"), {"h": H})
    q = text(
        "insert into package(id,content_sha256,rev,canonical,manifest) "
        "values (:id,:h,:rev,true,'{}')"
    )
    conn.execute(q, {"id": f"{H}:1", "h": H, "rev": 1})
    with pytest.raises(IntegrityError):
        conn.execute(q, {"id": f"{H}:2", "h": H, "rev": 2})


def test_one_job_per_processor_version_target(conn: Connection) -> None:
    q = text("insert into job(id,processor,version,target) values (:id,'chunk','1',:t)")
    conn.execute(q, {"id": "j1", "t": "x"})
    with pytest.raises(IntegrityError):
        conn.execute(q, {"id": "j2", "t": "x"})
    conn.rollback()


def test_ids_are_stable() -> None:
    assert ids.job_id("chunk", "1", "x") == ids.job_id("chunk", "1", "x")
    assert ids.job_id("chunk", "1", "x") != ids.job_id("chunk", "2", "x")
    assert ids.location_id("s", "/a", H) != ids.location_id("s", "/a", "b" * 64)
    assert ids.package_id(H, 2) == f"{H}:2"


def test_schemas() -> None:
    good = {
        "content_sha256": H,
        "rev": 1,
        "source_type": "pdf",
        "title": "t",
        "parser": {"name": "docling", "version": "1"},
        "files": ["content.md"],
        "created_at": "2026-01-01T00:00:00Z",
    }
    validate_manifest(good)
    with pytest.raises(ValidationError):
        validate_manifest({k: v for k, v in good.items() if k != "title"})
    validate_job(
        {"processor": "p", "version": "1", "target": "t", "status": "pending", "attempts": 0}
    )
    with pytest.raises(ValidationError):
        validate_job(
            {"processor": "p", "version": "1", "target": "t", "status": "bogus", "attempts": 0}
        )
