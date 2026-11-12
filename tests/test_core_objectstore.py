import uuid
from collections.abc import Iterator

import pytest
from jsonschema import ValidationError
from lake_core.objectstore import (
    ObjectStore,
    PackageExists,
    get_original,
    put_original,
    read_package,
    write_package,
)
from moto.server import ThreadedMotoServer

H = "c" * 64


@pytest.fixture
def store() -> Iterator[ObjectStore]:
    server = ThreadedMotoServer(port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    s = ObjectStore(f"http://{host}:{port}", "k", "s", f"lake-{uuid.uuid4().hex[:8]}")
    s.ensure_bucket()
    yield s
    server.stop()


def manifest(rev: int = 1) -> dict[str, object]:
    return {
        "content_sha256": H,
        "rev": rev,
        "source_type": "pdf",
        "title": "t",
        "parser": {"name": "docling", "version": "1"},
        "files": ["content.md", "blob.bin"],
        "created_at": "2026-01-01T00:00:00Z",
    }


def test_round_trip_byte_for_byte(store: ObjectStore) -> None:
    files = {"content.md": "héllo\n".encode(), "blob.bin": bytes(range(256))}
    write_package(store, manifest(), files)
    m, got = read_package(store, H, 1)
    assert got == files and m["title"] == "t"
    put_original(store, H, b"\x00\x01raw")
    assert get_original(store, H) == b"\x00\x01raw"


def test_existing_rev_rejected_new_rev_ok(store: ObjectStore) -> None:
    files = {"content.md": b"a", "blob.bin": b"b"}
    write_package(store, manifest(), files)
    with pytest.raises(PackageExists):
        write_package(store, manifest(), files)
    write_package(store, manifest(2), files)


def test_bad_manifest_rejected_and_nothing_written(store: ObjectStore) -> None:
    bad = manifest()
    del bad["title"]
    with pytest.raises(ValidationError):
        write_package(store, bad, {"content.md": b"a", "blob.bin": b"b"})
    assert not store.exists(f"packages/{H}/1/content.md")
