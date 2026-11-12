from lake_core.db import make_engine, upgrade_to_head
from lake_core.objectstore import ObjectStore
from lake_ingest.adapter import Item
from lake_ingest.registrar import Registrar
from lake_processors.chunk import ChunkProcessor, split_markdown
from lake_processors.contract import Context, Registry
from lake_processors.loop import run_until_idle
from sqlalchemy import text

MD = (
    "# Book\n\nintro\n\n## Ch1\n\nalpha\n\nbeta\n\n```\n# not a heading\n\ncode\n```\n\n## Ch2\n\n"
    + ("x" * 2500)
)


def test_split_tracks_heading_path_and_respects_limit() -> None:
    pieces = split_markdown(MD)
    assert pieces[0].section == "Book" and pieces[1].section == "Book > Ch1"
    assert "# not a heading" in pieces[1].text  # fenced code is not split into headings
    assert pieces[-1].section == "Book > Ch2"
    assert all(len(p.text) <= 1200 for p in pieces) and len(pieces) >= 5


def test_chunk_job_writes_rows_once_and_queues_embed(db_url: str, store: ObjectStore) -> None:
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    Registrar(eng, store).register(Item(MD.encode(), "/b.md", "upload", markdown=MD))
    reg = Registry()
    reg.add(ChunkProcessor())
    run_until_idle(Context(eng, store), reg)
    with eng.connect() as c:
        n = c.execute(text("select count(*) from chunk")).scalar_one()
        assert n >= 5
        pid = c.execute(text("select id from package")).scalar_one()
        assert c.execute(text("select count(*) from job where processor='embed'")).scalar_one() == 1
    ChunkProcessor().run(pid, Context(eng, store))  # forced rerun
    with eng.connect() as c:
        assert c.execute(text("select count(*) from chunk")).scalar_one() == n
