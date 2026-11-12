"""Connect to Postgres and the object store, create a bucket, enable pgvector.

Reads LAKE_DATABASE_URL, LAKE_S3_ENDPOINT, LAKE_S3_KEY, LAKE_S3_SECRET, LAKE_S3_BUCKET.
Deploy tooling, not package code: the layer rules and the settings rule (only lake_core
reads the environment) apply to packages/ only.
"""

import os
import sys

import boto3
import psycopg


def main() -> None:
    with psycopg.connect(os.environ["LAKE_DATABASE_URL"], autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        row = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
        assert row, "pgvector not enabled"
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["LAKE_S3_ENDPOINT"],
        aws_access_key_id=os.environ["LAKE_S3_KEY"],
        aws_secret_access_key=os.environ["LAKE_S3_SECRET"],
        region_name="us-east-1",
    )
    bucket = os.environ.get("LAKE_S3_BUCKET", "lake")
    if bucket not in [b["Name"] for b in s3.list_buckets()["Buckets"]]:
        s3.create_bucket(Bucket=bucket)
    print(f"ok: pgvector {row[0]}, bucket {bucket}")


if __name__ == "__main__":
    sys.exit(main())
