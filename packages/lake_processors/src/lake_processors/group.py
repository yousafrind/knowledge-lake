"""group: propose version families and near-duplicate text. Suggestions wait for review."""

import re
from pathlib import PurePosixPath

from sqlalchemy import text

from lake_processors.contract import Context

NEAR_DUPLICATE_DISTANCE = 0.1  # cosine distance between whole-document average vectors
NOISE = re.compile(
    r"([ _.-]*(v\d+|ver\d+|final\d*|copy|draft|new|old|rev\d+|\(\d+\)|\d{4}-\d{2}-\d{2}))+$", re.I
)


def family_key(path: str) -> str:
    """report_v2_final.docx -> '<folder>/report': same folder, same stem minus version words."""
    p = PurePosixPath(path)
    stem = NOISE.sub("", p.stem).strip(" _.-").lower()
    return f"{p.parent}/{stem}"


def _add_group(c, kind: str, key: str, shas: list[str], confidence: float, rule: str) -> None:  # type: ignore[no-untyped-def]
    gid = c.execute(
        text(
            "insert into doc_group(kind,key,confidence,rule) values (:k,:key,:c,:r) "
            "on conflict (kind,key) do update set confidence=excluded.confidence returning id"
        ),
        {"k": kind, "key": key, "c": confidence, "r": rule},
    ).scalar_one()
    for sha in shas:
        c.execute(
            text(
                "insert into doc_group_member(group_id,content_sha) values (:g,:s) "
                "on conflict do nothing"
            ),
            {"g": gid, "s": sha},
        )


class GroupProcessor:
    name = "group"
    version = "1"
    cost = "cpu"

    def __init__(self, model: str) -> None:
        self.model = model

    def run(self, target: str, ctx: Context) -> None:
        sha = target.rsplit(":", 1)[0]
        with ctx.engine.begin() as c:
            # exact duplicates: one content row with several locations
            n = c.execute(
                text("select count(*) from location where content_sha256=:h"), {"h": sha}
            ).scalar_one()
            if n > 1:
                _add_group(c, "exact_duplicate", sha, [sha], 1.0, "content hash")
                c.execute(
                    text(
                        "update doc_group set status='accepted' where kind='exact_duplicate' and key=:k"
                    ),
                    {"k": sha},
                )
            # version families: same folder, same stem apart from version words
            mine = c.execute(
                text("select path from location where content_sha256=:h"), {"h": sha}
            ).all()
            for (path,) in mine:
                key = family_key(path)
                folder = str(PurePosixPath(path).parent).rstrip("/") + "/"
                rows = c.execute(
                    text("select path, content_sha256 from location where path like :l"),
                    {"l": folder + "%"},
                ).all()
                members = {r.content_sha256 for r in rows if family_key(r.path) == key}
                if len(members) > 1:
                    _add_group(c, "version_family", key, sorted(members), 0.7, "name stem")
            # near-duplicates by meaning: closest other document by average vector
            near = c.execute(
                text(
                    """
                    with mine as (select avg(e.vec) v from embedding e join chunk ch on ch.id=e.chunk_id
                                  join package p on p.id=ch.package_id
                                  where p.content_sha256=:h and p.canonical and e.model=:m),
                    others as (select p.content_sha256 s, avg(e.vec) v from embedding e
                               join chunk ch on ch.id=e.chunk_id join package p on p.id=ch.package_id
                               where p.canonical and p.content_sha256<>:h and e.model=:m
                               group by p.content_sha256)
                    select s, (others.v <=> (select v from mine)) d from others
                    where (select v from mine) is not null order by d limit 5
                    """
                ),
                {"h": sha, "m": self.model},
            ).all()
            for other, dist in near:
                if dist <= NEAR_DUPLICATE_DISTANCE:
                    key = ":".join(sorted([sha, other]))
                    _add_group(
                        c,
                        "near_duplicate",
                        key,
                        [sha, other],
                        round(1 - float(dist), 3),
                        "embedding",
                    )
