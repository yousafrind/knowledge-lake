"""Job creation shared by the registrar and processors. Same work twice = one row."""

from sqlalchemy import Connection, text

from lake_core.ids import job_id


def enqueue_job(c: Connection, processor: str, target: str, version: str = "1") -> None:
    c.execute(
        text(
            "insert into job(id,processor,version,target) values (:id,:p,:v,:t) "
            "on conflict do nothing"
        ),
        {"id": job_id(processor, version, target), "p": processor, "v": version, "t": target},
    )
