"""quarantine: files held back because a secret was found

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"

SQL = """
CREATE TABLE quarantine (
  content_sha text PRIMARY KEY REFERENCES content(sha256),
  reasons jsonb NOT NULL,
  status text NOT NULL DEFAULT 'held' CHECK (status IN ('held','released')),
  created_at timestamptz NOT NULL DEFAULT now()
);
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    op.execute("DROP TABLE quarantine")
