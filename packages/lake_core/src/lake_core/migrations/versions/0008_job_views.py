"""job views: counts by processor and status, and the jobs that need a human

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"

SQL = """
CREATE VIEW job_counts AS
  SELECT processor, status, count(*) AS n FROM job GROUP BY processor, status;

CREATE VIEW job_problems AS
  SELECT id, processor, target, status, attempts, error, lease_until
  FROM job
  WHERE status IN ('failed', 'dead') OR (status = 'running' AND lease_until < now());
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    op.execute("DROP VIEW job_problems; DROP VIEW job_counts")
