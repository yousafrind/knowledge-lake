"""code references and imports (tree-sitter name matching), file recency

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"

SQL = """
ALTER TABLE code_repo_file ADD COLUMN seen_at timestamptz NOT NULL DEFAULT now();

CREATE TABLE code_ref (
  content_sha text NOT NULL REFERENCES content(sha256),
  name text NOT NULL,
  line int NOT NULL,
  kind text NOT NULL CHECK (kind IN ('call','ref')),
  PRIMARY KEY (content_sha, name, line, kind)
);
CREATE INDEX code_ref_name ON code_ref(name);

CREATE TABLE code_import (
  content_sha text NOT NULL REFERENCES content(sha256),
  module text NOT NULL,
  PRIMARY KEY (content_sha, module)
);
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    op.execute("DROP TABLE code_import, code_ref; ALTER TABLE code_repo_file DROP COLUMN seen_at")
