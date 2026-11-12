from lake_core.db import make_engine, upgrade_to_head
from lake_core.embedding import HashEmbedder, to_pgvector
from lake_core.objectstore import ObjectStore
from lake_ingest.adapter import Item
from lake_ingest.registrar import Registrar
from lake_processors.chunk import ChunkProcessor
from lake_processors.contract import Context, Registry
from lake_processors.embed import EmbedProcessor
from lake_processors.loop import run_until_idle
from sqlalchemy import text

MD = "# Doc\n\nPostgres replication copies data between servers.\n\n## Cooking\n\nBake the bread."


def test_embed_and_full_text(db_url: str, store: ObjectStore) -> None:
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    Registrar(eng, store).register(Item(MD.encode(), "/d.md", "upload", markdown=MD))
    reg = Registry()
    reg.add(ChunkProcessor())
    emb = HashEmbedder()
    reg.add(EmbedProcessor(emb))
    ctx = Context(eng, store)
    run_until_idle(ctx, reg)
    with eng.connect() as c:
        chunks = c.execute(text("select count(*) from chunk")).scalar_one()
        assert chunks == 2
        assert c.execute(text("select count(*) from embedding")).scalar_one() == chunks
        # vector search finds the replication chunk first
        q = to_pgvector(emb.embed(["replication servers"])[0])
        top = c.execute(
            text(
                "select ch.section from embedding e join chunk ch on ch.id=e.chunk_id "
                "order by e.vec <=> cast(:q as vector) limit 1"
            ),
            {"q": q},
        ).scalar_one()
        assert top == "Doc"
        # full-text finds the bread chunk
        hit = c.execute(
            text("select section from chunk where tsv @@ plainto_tsquery('english','bread')")
        ).scalar_one()
        assert hit == "Doc > Cooking"
    with eng.connect() as c2:
        pid = c2.execute(text("select id from package")).scalar_one()
    reg.get("embed").run(pid, ctx)  # forced rerun
    with eng.connect() as c2:
        assert c2.execute(text("select count(*) from embedding")).scalar_one() == chunks
