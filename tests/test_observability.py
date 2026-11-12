import json
import logging

from lake_core.db import make_engine, upgrade_to_head
from lake_core.jobs import enqueue_job
from lake_core.licences import installed, violations
from lake_core.logs import JsonFormatter
from lake_processors.contract import Context, Registry
from lake_processors.loop import run_until_idle
from sqlalchemy import text

SHA = "a" * 64


class Boom:
    name = "boom"

    def run(self, target: str, ctx: Context) -> None:
        raise RuntimeError("nope")


class Fine:
    name = "fine"

    def run(self, target: str, ctx: Context) -> None:
        pass


def test_job_counts_and_problems_views(db_url: str, store, caplog) -> None:  # type: ignore[no-untyped-def]
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    with eng.begin() as c:
        c.execute(text("insert into content values (:s, 1, 'text')"), {"s": SHA})
        enqueue_job(c, "fine", SHA)
        enqueue_job(c, "boom", f"{SHA}:1")
    reg = Registry()
    reg.add(Fine())
    reg.add(Boom())
    with caplog.at_level(logging.INFO):
        run_until_idle(Context(eng, store), reg, max_attempts=1)
    with eng.connect() as c:
        counts = {(r.processor, r.status): r.n for r in c.execute(text("select * from job_counts"))}
        problems = c.execute(text("select processor, error from job_problems")).all()
    assert counts == {("fine", "done"): 1, ("boom", "dead"): 1}
    assert problems == [("boom", "RuntimeError: nope")]

    lines = [json.loads(JsonFormatter().format(r)) for r in caplog.records if r.name == "lake.jobs"]
    assert len(lines) == 2
    assert all(ln["job_id"] and ln["content_sha256"] == SHA for ln in lines)
    assert {ln["outcome"] for ln in lines} == {"done", "failed"}


def test_licence_check_flags_gpl_but_not_lgpl() -> None:
    pkgs = [
        ("a", ["MIT License"]),
        ("b", ["GNU Affero General Public License v3"]),
        ("c", ["License :: OSI Approved :: GNU General Public License v3 (GPLv3)"]),
        ("d", ["GNU Lesser General Public License v3 (LGPLv3)"]),
        ("e", ["AGPL-3.0-only"]),
        ("f", ["Apache-2.0"]),
    ]
    assert [n for n, _ in violations(pkgs)] == ["b", "c", "e"]
    assert [n for n, _ in violations(pkgs, allowed=frozenset({"b"}))] == ["c", "e"]


def test_licence_check_reads_the_real_environment() -> None:
    pkgs = list(installed())
    assert any(n.lower() == "sqlalchemy" for n, _ in pkgs)
    print([v for v in violations(pkgs)])  # visible with -s; policy decisions live in the register
