from lake_cli.main import build_registry
from lake_core.db import make_engine, upgrade_to_head
from lake_core.objectstore import ObjectStore
from lake_ingest.adapter import Item
from lake_ingest.registrar import Registrar
from lake_ingest.types import detect_type
from lake_processors.classify import effective_labels, load_rules
from lake_processors.contract import Context
from lake_processors.group import family_key
from lake_processors.loop import run_until_idle
from sqlalchemy import text

RULES = 'rules:\n  - path: "**/books/**"\n    labels: {kind: book}\n'


def test_type_detection_trusts_content_for_binaries() -> None:
    assert detect_type(b"%PDF-1.4\n" + b"x" * 200, "/mislabeled.txt") == "pdf"
    assert detect_type(b"# hi", "/a.md") == "markdown"
    assert detect_type(b"plain words here " * 20, "/noext") in {"text", "markdown"}


def test_family_key_ignores_version_words() -> None:
    keys = {
        family_key(p) for p in ["/d/report_v1.docx", "/d/report_final.docx", "/d/Report (2).docx"]
    }
    assert keys == {"/d/report"} and family_key("/d/other.docx") != "/d/report"


def build(db_url: str, store: ObjectStore):  # type: ignore[no-untyped-def]
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    reg = Registrar(eng, store)
    body = "# Raft\n\nleader election needs a majority of votes in the cluster"
    reg.register(Item(body.encode(), "/lib/books/raft_v1.md", "disk", markdown=body))
    reg.register(
        Item(body.encode(), "/lib/books/raft_final.md", "disk", markdown=body)
    )  # same bytes
    other = body + " today"
    reg.register(Item(other.encode(), "/lib/books/raft_v2.md", "disk", markdown=other))
    reg.register(
        Item(
            b"# Bread\n\nflour water salt",
            "/lib/bread.md",
            "disk",
            markdown="# Bread\n\nflour water salt",
        )
    )
    ctx = Context(eng, store)
    run_until_idle(ctx, build_registry("hash", rules_yaml=RULES))
    return eng


def test_labels_follow_rules_and_manual_wins(db_url: str, store: ObjectStore) -> None:
    eng = build(db_url, store)
    with eng.begin() as c:
        sha = c.execute(
            text("select content_sha256 from location where path='/lib/books/raft_v2.md'")
        ).scalar_one()
        labels = effective_labels(c, sha)
        assert labels["kind"] == "book" and labels["type"] == "markdown"
        c.execute(text("insert into label values (:h,'kind','paper','manual',1)"), {"h": sha})
    with eng.begin() as c:
        assert effective_labels(c, sha)["kind"] == "paper"
    # re-running classification must not overwrite the manual decision
    from lake_processors.classify import ClassifyProcessor

    ClassifyProcessor(load_rules(RULES)).run(f"{sha}:1", Context(eng, store))
    with eng.connect() as c:
        assert effective_labels(c, sha)["kind"] == "paper"
        assert (
            c.execute(
                text(
                    "select value from label where content_sha=:h and key='kind' and source='rule'"
                ),
                {"h": sha},
            ).scalar_one()
            == "book"
        )


def test_groups_exact_duplicates_families_and_near_duplicates(
    db_url: str, store: ObjectStore
) -> None:
    eng = build(db_url, store)
    with eng.connect() as c:
        groups = {
            (g.kind, g.status): g.n
            for g in c.execute(
                text(
                    "select g.kind, g.status, count(m.content_sha) n from doc_group g "
                    "join doc_group_member m on m.group_id=g.id group by g.id, g.kind, g.status"
                )
            )
        }
    assert groups[("exact_duplicate", "accepted")] == 1  # raft_v1 and raft_final share bytes
    assert groups[("version_family", "suggested")] == 2  # two distinct contents in the raft family
    assert ("near_duplicate", "suggested") in groups
