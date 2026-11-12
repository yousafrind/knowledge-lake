#!/bin/sh
# Nightly backup for stage B: Postgres dump + mirror of the object store to a second target.
# Cron: 15 2 * * *  /opt/lake/deploy/stage-b/backup.sh
# Needs: LAKE_DATABASE_URL, and for the mirror the `mc` client with aliases `lake` (local MinIO)
# and `offsite` (a second provider). Not run in CI: needs a real host. Keeps 14 dumps.
set -eu
DIR="${LAKE_BACKUP_DIR:-/var/backups/lake}"
mkdir -p "$DIR"
uv run lake backup "$DIR/lake-$(date +%F).dump"
mc mirror --overwrite "lake/${LAKE_S3_BUCKET:-lake}" "offsite/${LAKE_S3_BUCKET:-lake}-backup"
ls -1t "$DIR"/lake-*.dump | tail -n +15 | xargs -r rm --
