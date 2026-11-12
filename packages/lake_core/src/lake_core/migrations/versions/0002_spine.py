"""spine tables: source, content, location, package, chunk, embedding, job

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"

# ponytail: embedding dimension fixed at 384 (small local models). Changing the model
# to another size needs a new migration and a re-embed; derived data is rebuildable.
SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE source (
  id serial PRIMARY KEY,
  name text NOT NULL UNIQUE,
  kind text NOT NULL,
  config jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE content (
  sha256 text PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size bigint NOT NULL CHECK (size >= 0),
  source_type text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE location (
  id text PRIMARY KEY,
  source_id int NOT NULL REFERENCES source(id),
  path text NOT NULL,
  content_sha256 text NOT NULL REFERENCES content(sha256),
  mtime timestamptz,
  seen_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_id, path, content_sha256)
);
CREATE INDEX location_content ON location(content_sha256);

CREATE TABLE package (
  id text PRIMARY KEY,
  content_sha256 text NOT NULL REFERENCES content(sha256),
  rev int NOT NULL CHECK (rev >= 1),
  canonical boolean NOT NULL DEFAULT false,
  tier text NOT NULL DEFAULT 'original' CHECK (tier IN ('original','derived')),
  manifest jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (content_sha256, rev)
);
CREATE UNIQUE INDEX one_canonical_package ON package(content_sha256) WHERE canonical;

CREATE TABLE chunk (
  id text PRIMARY KEY,
  package_id text NOT NULL REFERENCES package(id) ON DELETE CASCADE,
  ordinal int NOT NULL,
  chunker_version text NOT NULL,
  section text,
  text text NOT NULL,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
  UNIQUE (package_id, ordinal, chunker_version)
);
CREATE INDEX chunk_tsv ON chunk USING gin(tsv);

CREATE TABLE embedding (
  chunk_id text NOT NULL REFERENCES chunk(id) ON DELETE CASCADE,
  model text NOT NULL,
  vec vector(384) NOT NULL,
  PRIMARY KEY (chunk_id, model)
);
CREATE INDEX embedding_hnsw ON embedding USING hnsw (vec vector_cosine_ops);

CREATE TABLE job (
  id text PRIMARY KEY,
  processor text NOT NULL,
  version text NOT NULL,
  target text NOT NULL,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','running','done','failed','dead')),
  attempts int NOT NULL DEFAULT 0,
  run_after timestamptz NOT NULL DEFAULT now(),
  lease_until timestamptz,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (processor, version, target)
);
CREATE INDEX job_claim ON job(status, run_after);
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    op.execute("DROP TABLE job, embedding, chunk, package, location, content, source CASCADE")
