# ADR 0001: Processor.run takes a target string and a context

**Status:** accepted (W-007)

**Was:** `run(package: Package, db: Session)` in the architecture's processor contract.

**Now:** `run(target: str, ctx: Context)` where `Context` holds the engine and the object store.

**Why:** the first processor (`parse`) runs before any package exists, so a `Package` argument cannot be passed. The job's `target` is a content hash (parse) or a package id (later steps); each processor loads what it needs from `ctx`. Everything else in the contract is unchanged: idempotent, versioned, one `cost` class.
