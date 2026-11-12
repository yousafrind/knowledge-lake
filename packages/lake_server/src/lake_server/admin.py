"""Review queue, sources and jobs: the queries behind those GUI screens."""

from typing import Any

from sqlalchemy import Engine, text


def review_items(engine: Engine) -> dict[str, list[Any]]:
    with engine.connect() as c:
        groups = c.execute(
            text(
                "select g.id, g.kind, g.key, g.confidence, g.rule, "
                "array_agg(m.content_sha order by m.content_sha) as members, "
                "array_agg(coalesce(p.manifest->>'title', m.content_sha) order by m.content_sha) "
                "as titles from doc_group g join doc_group_member m on m.group_id=g.id "
                "left join package p on p.content_sha256=m.content_sha and p.canonical "
                "where g.status='suggested' group by g.id order by g.id"
            )
        ).all()
        qa = c.execute(
            text(
                "select content_sha256 as sha, manifest->>'title' as title, "
                "manifest->'qa'->'reasons' as reasons from package "
                "where canonical and (manifest->'qa'->>'needs_review')::boolean is true"
            )
        ).all()
    return {"groups": list(groups), "qa": list(qa)}


def decide_group(engine: Engine, group_id: int, accept: bool) -> None:
    with engine.begin() as c:
        c.execute(
            text("update doc_group set status=:s where id=:i"),
            {"s": "accepted" if accept else "rejected", "i": group_id},
        )


def jobs_overview(engine: Engine) -> dict[str, Any]:
    with engine.connect() as c:
        counts = c.execute(
            text("select processor, status, count(*) n from job group by 1,2 order by 1,2")
        ).all()
        problems = c.execute(
            text(
                "select id, processor, target, status, attempts, error from job "
                "where status in ('failed','dead') or (status='pending' and error is not null) "
                "order by created_at desc limit 50"
            )
        ).all()
        sources = c.execute(
            text(
                "select s.name, count(distinct l.content_sha256) docs, count(l.id) locations "
                "from source s left join location l on l.source_id=s.id group by s.name order by 1"
            )
        ).all()
    return {"counts": list(counts), "problems": list(problems), "sources": list(sources)}


def retry_job(engine: Engine, job_id: str) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "update job set status='pending', attempts=0, run_after=now(), lease_until=null "
                "where id=:i and status in ('failed','dead','pending')"
            ),
            {"i": job_id},
        )
