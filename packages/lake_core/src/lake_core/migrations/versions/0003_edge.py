"""edge: deterministic links between documents

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"

SQL = """
CREATE TABLE edge (
  src_sha text NOT NULL REFERENCES content(sha256),
  dst_ref text NOT NULL,
  dst_sha text REFERENCES content(sha256),
  kind text NOT NULL DEFAULT 'link',
  anchor text,
  UNIQUE (src_sha, dst_ref, kind)
);
CREATE INDEX edge_dst ON edge(dst_sha);
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    op.execute("DROP TABLE edge")
