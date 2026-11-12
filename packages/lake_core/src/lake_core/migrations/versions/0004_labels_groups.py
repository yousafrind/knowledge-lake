"""labels and groups (satellites on the content hash)

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"

SQL = """
CREATE TABLE label (
  content_sha text NOT NULL REFERENCES content(sha256),
  key text NOT NULL,
  value text NOT NULL,
  source text NOT NULL CHECK (source IN ('manual','rule','folder','content')),
  confidence real NOT NULL DEFAULT 1.0,
  PRIMARY KEY (content_sha, key, source)
);

CREATE TABLE doc_group (
  id serial PRIMARY KEY,
  kind text NOT NULL,
  key text NOT NULL,
  status text NOT NULL DEFAULT 'suggested' CHECK (status IN ('suggested','accepted','rejected')),
  confidence real NOT NULL DEFAULT 1.0,
  rule text,
  UNIQUE (kind, key)
);

CREATE TABLE doc_group_member (
  group_id int NOT NULL REFERENCES doc_group(id) ON DELETE CASCADE,
  content_sha text NOT NULL REFERENCES content(sha256),
  PRIMARY KEY (group_id, content_sha)
);
CREATE INDEX doc_group_member_sha ON doc_group_member(content_sha);
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    op.execute("DROP TABLE doc_group_member, doc_group, label")
