"""code index: repos, files per commit, symbols

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"

SQL = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE code_repo (
  id serial PRIMARY KEY,
  root text NOT NULL UNIQUE,
  name text NOT NULL
);

CREATE TABLE code_repo_file (
  repo_id int NOT NULL REFERENCES code_repo(id) ON DELETE CASCADE,
  commit_sha text NOT NULL,
  path text NOT NULL,
  content_sha text NOT NULL REFERENCES content(sha256),
  PRIMARY KEY (repo_id, commit_sha, path)
);
CREATE INDEX code_repo_file_content ON code_repo_file(content_sha);

CREATE TABLE code_symbol (
  id serial PRIMARY KEY,
  content_sha text NOT NULL REFERENCES content(sha256),
  name text NOT NULL,
  kind text NOT NULL,
  signature text NOT NULL,
  doc text NOT NULL DEFAULT '',
  start_line int NOT NULL,
  end_line int NOT NULL,
  parent text,
  UNIQUE (content_sha, name, start_line)
);
CREATE INDEX code_symbol_name ON code_symbol USING gin (name gin_trgm_ops);
CREATE INDEX code_symbol_content ON code_symbol(content_sha);
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    op.execute("DROP TABLE code_symbol, code_repo_file, code_repo")
