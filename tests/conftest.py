import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest

ADMIN = os.environ.get("LAKE_TEST_ADMIN_URL", "postgresql://lake:lake@localhost:5432/postgres")


@pytest.fixture
def db_url() -> Iterator[str]:
    """A fresh, empty database, dropped afterwards."""
    name = f"lake_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(ADMIN, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    yield ADMIN.rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://") + f"/{name}"
    with psycopg.connect(ADMIN, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
