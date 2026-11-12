import threading
from typing import Literal

from lake_core.db import make_engine, upgrade_to_head
from lake_core.ids import job_id
from lake_core.objectstore import ObjectStore
from lake_processors.contract import Context, Registry
from lake_processors.loop import claim, run_once, run_until_idle
from sqlalchemy import Engine, text


def enqueue(engine: Engine, processor: str, target: str) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "insert into job(id,processor,version,target) values (:i,:p,'1',:t) "
                "on conflict do nothing"
            ),
            {"i": job_id(processor, "1", target), "p": processor, "t": target},
        )


class Recorder:
    name = "rec"
    version = "1"
    cost: Literal["cpu"] = "cpu"

    def __init__(self) -> None:
        self.seen: list[str] = []

    def run(self, target: str, ctx: Context) -> None:
        self.seen.append(target)


class Failing(Recorder):
    name = "fail"

    def run(self, target: str, ctx: Context) -> None:
        raise RuntimeError("boom")


def test_two_workers_never_claim_the_same_job(db_url: str) -> None:
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    for i in range(20):
        enqueue(eng, "rec", str(i))
    got: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        while (j := claim(eng, ["rec"])) is not None:
            with lock:
                got.append(j.id)

    ts = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(got) == 20 and len(set(got)) == 20


def test_crashed_workers_lease_expires_and_job_reruns(db_url: str, store: ObjectStore) -> None:
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    enqueue(eng, "rec", "x")
    assert claim(eng, ["rec"], lease_seconds=0) is not None  # worker "crashes" here
    assert claim(eng, ["rec"], lease_seconds=300) is not None  # lease expired: claimable again
    assert claim(eng, ["rec"]) is None  # now held by a live lease


def test_always_failing_processor_ends_dead(db_url: str, store: ObjectStore) -> None:
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    enqueue(eng, "fail", "x")
    reg = Registry()
    reg.add(Failing())
    n = run_until_idle(Context(eng, store), reg, max_attempts=3, backoff=0)
    assert n == 3
    with eng.connect() as c:
        row = c.execute(text("select status, attempts, error from job")).one()
    assert row == ("dead", 3, "RuntimeError: boom")


def test_rerun_creates_no_duplicates(db_url: str, store: ObjectStore) -> None:
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    rec = Recorder()
    reg = Registry()
    reg.add(rec)
    enqueue(eng, "rec", "x")
    enqueue(eng, "rec", "x")
    assert run_once(Context(eng, store), reg) and not run_once(Context(eng, store), reg)
    enqueue(eng, "rec", "x")  # same processor+version+target: still one row, already done
    assert not run_once(Context(eng, store), reg)
    with eng.connect() as c:
        assert c.execute(text("select count(*) from job")).scalar_one() == 1
    assert rec.seen == ["x"]
