import os
import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING

import psycopg
import pytest

if TYPE_CHECKING:
    from lake_core.objectstore import ObjectStore

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


@pytest.fixture
def store() -> Iterator["ObjectStore"]:
    from lake_core.objectstore import ObjectStore
    from moto.server import ThreadedMotoServer

    server = ThreadedMotoServer(port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    s = ObjectStore(f"http://{host}:{port}", "k", "s", f"lake-{uuid.uuid4().hex[:8]}")
    s.ensure_bucket()
    yield s
    server.stop()
