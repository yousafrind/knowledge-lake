"""Object store client and package IO, using the runtime-layout key scheme.

originals/<sha[:2]>/<sha>            raw bytes
packages/<sha>/<rev>/<file>          manifest.json plus the package files
"""

import json
from typing import Any

import boto3
from botocore.exceptions import ClientError

from lake_core.schemas import validate_manifest


class PackageExists(Exception):
    pass


class ObjectStore:
    def __init__(self, endpoint: str, key: str, secret: str, bucket: str) -> None:
        self.bucket = bucket
        self.s3: Any = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            region_name="us-east-1",
        )

    def ensure_bucket(self) -> None:
        names = [b["Name"] for b in self.s3.list_buckets()["Buckets"]]
        if self.bucket not in names:
            self.s3.create_bucket(Bucket=self.bucket)

    def put(self, key: str, data: bytes) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data)

    def get(self, key: str) -> bytes:
        body: bytes = self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        return body

    def exists(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            return False
        return True


def original_key(sha: str) -> str:
    return f"originals/{sha[:2]}/{sha}"


def package_prefix(sha: str, rev: int) -> str:
    return f"packages/{sha}/{rev}/"


def put_original(store: ObjectStore, sha: str, data: bytes) -> None:
    store.put(original_key(sha), data)  # same hash = same bytes, so overwrite is harmless


def get_original(store: ObjectStore, sha: str) -> bytes:
    return store.get(original_key(sha))


def write_package(store: ObjectStore, manifest: dict[str, Any], files: dict[str, bytes]) -> None:
    """Validate, then write files first and manifest.json last (its presence = complete)."""
    validate_manifest(manifest)
    prefix = package_prefix(manifest["content_sha256"], manifest["rev"])
    # ponytail: check-then-write; fine for one writer, use a conditional put if that changes.
    if store.exists(prefix + "manifest.json"):
        raise PackageExists(prefix)
    for name, data in files.items():
        store.put(prefix + name, data)
    store.put(prefix + "manifest.json", json.dumps(manifest).encode())


def read_package(store: ObjectStore, sha: str, rev: int) -> tuple[dict[str, Any], dict[str, bytes]]:
    prefix = package_prefix(sha, rev)
    manifest: dict[str, Any] = json.loads(store.get(prefix + "manifest.json"))
    files = {name: store.get(prefix + name) for name in manifest["files"]}
    return manifest, files
