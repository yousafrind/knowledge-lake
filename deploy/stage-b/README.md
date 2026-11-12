# Stage B: private always-on host

Same `compose.yaml` as stage A, run on an always-on machine reached only over a VPN or LAN.

1. Copy the repo and a `.env` (git-ignored) with real passwords to the host.
2. Bind to the VPN/LAN interface only: set the `ports:` host addresses in `compose.yaml` to the
   VPN address instead of `127.0.0.1`. Postgres and MinIO must never listen on a public interface.
3. Set `LAKE_GUI_PASSWORD` (the web GUI stays off until it is set) and start with `make up`.
4. Install the nightly backup: add `backup.sh` to cron (see the header of the script).

## Restore drill (monthly)

```sh
createdb -h <host> lake_scratch          # an empty scratch database
uv run lake restore-drill /var/backups/lake/lake-YYYY-MM-DD.dump \
    postgresql+psycopg://lake:<pw>@<host>/lake_scratch
```

It restores only the tables that cannot be rebuilt (source, content, location, package,
quarantine, labels), rebuilds chunks, embeddings, links and groups from the packages in the
object store, and compares row counts with the live lake. Exit code 1 means they differ.
Drop the scratch database afterwards. Run it against a restored copy of the *object store* too
(`mc mirror offsite/... lake/...` into a scratch bucket via `LAKE_S3_BUCKET`) to prove the second
copy is usable.

Untested here: no Docker or MinIO in the build sandbox, so `compose.yaml` on a real host, `mc mirror`
and cron are unverified. The drill itself is tested (`tests/test_restore_drill.py`) against local
Postgres and an in-memory S3.
