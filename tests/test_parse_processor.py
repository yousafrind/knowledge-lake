from lake_core.db import make_engine, upgrade_to_head
from lake_core.objectstore import ObjectStore, read_package
from lake_ingest.adapter import Item
from lake_ingest.registrar import Registrar
from lake_parsers.plain import PlainTextParser
from lake_processors.contract import Context, Registry
from lake_processors.loop import run_until_idle
from lake_processors.parse import ParseProcessor
from sqlalchemy import text


def test_parse_writes_package_and_queues_chunk(db_url: str, store: ObjectStore) -> None:
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    r = Registrar(eng, store).register(Item(b"fake pdf text", "/doc.pdf", "upload"))
    reg = Registry()
    reg.add(ParseProcessor({}, PlainTextParser()))
    assert run_until_idle(Context(eng, store), reg) == 1
    manifest, files = read_package(store, r.content_sha256, 1)
    assert files["content.md"] == b"fake pdf text" and manifest["parser"]["name"] == "plain"
    with eng.connect() as c:
        assert c.execute(text("select count(*) from package where canonical")).scalar_one() == 1
        assert c.execute(text("select processor from job where processor='chunk'")).scalar_one()
        # rerun: new parse job row cannot exist (same id), and a forced rerun adds nothing
        reg.get("parse").run(r.content_sha256, Context(eng, store))
        assert c.execute(text("select count(*) from package")).scalar_one() == 1
