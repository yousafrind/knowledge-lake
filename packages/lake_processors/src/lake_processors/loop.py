"""The job loop: claim one job at a time from Postgres, run it, record the outcome."""

from dataclasses import dataclass

from sqlalchemy import Engine, text

from lake_processors.contract import Context, Registry

CLAIM = text(
    """
    update job set status='running', attempts = attempts + 1,
           lease_until = now() + make_interval(secs => :lease)
    where id = (
      select id from job
      where processor = any(:names)
        and ((status = 'pending' and run_after <= now())
             or (status = 'running' and lease_until < now()))
      order by run_after
      for update skip locked
      limit 1)
    returning id, processor, target, attempts
    """
)


@dataclass(frozen=True)
class Claimed:
    id: str
    processor: str
    target: str
    attempts: int


def claim(engine: Engine, names: list[str], lease_seconds: float = 300) -> Claimed | None:
    with engine.begin() as c:
        row = c.execute(CLAIM, {"names": names, "lease": lease_seconds}).first()
    return Claimed(*row) if row else None


def finish(
    engine: Engine, job: Claimed, error: str | None, max_attempts: int, backoff: float
) -> None:
    with engine.begin() as c:
        if error is None:
            c.execute(
                text("update job set status='done', lease_until=null, error=null where id=:i"),
                {"i": job.id},
            )
        elif job.attempts >= max_attempts:
            c.execute(
                text("update job set status='dead', lease_until=null, error=:e where id=:i"),
                {"i": job.id, "e": error},
            )
        else:
            c.execute(
                text(
                    "update job set status='pending', lease_until=null, error=:e, "
                    "run_after = now() + make_interval(secs => :b) where id=:i"
                ),
                {"i": job.id, "e": error, "b": backoff * 2 ** (job.attempts - 1)},
            )


def run_once(
    ctx: Context,
    registry: Registry,
    *,
    max_attempts: int = 5,
    backoff: float = 5,
    lease_seconds: float = 300,
) -> bool:
    """Claim and run one job. Returns False when there was nothing to do."""
    job = claim(ctx.engine, registry.names(), lease_seconds)
    if job is None:
        return False
    try:
        registry.get(job.processor).run(job.target, ctx)
        error = None
    except Exception as e:  # the loop records failures; retries are its job, not the processor's
        error = f"{type(e).__name__}: {e}"
    finish(ctx.engine, job, error, max_attempts, backoff)
    return True


def run_until_idle(ctx: Context, registry: Registry, **kw: float) -> int:
    n = 0
    while run_once(ctx, registry, **kw):  # type: ignore[arg-type]
        n += 1
    return n
