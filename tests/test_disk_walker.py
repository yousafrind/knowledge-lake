from pathlib import Path

from lake_ingest.disk import DiskAdapter

ROOT = Path(__file__).parent.parent / "evals" / "fixtures" / "disk_tree"
RULES = (Path(__file__).parent.parent / "config" / "lakeignore.default").read_text()


def names(items) -> list[str]:  # type: ignore[no-untyped-def]
    return sorted(Path(i.path).relative_to(ROOT.resolve()).as_posix() for i in items)


def test_walker_applies_default_lakeignore_and_gitignore_layers() -> None:
    d = DiskAdapter(RULES)
    got = names(d.scan(str(ROOT)))
    assert got == [
        ".lakeignore",
        "docs/keep.txt",
        "docs/notes.md",
        "proj/.gitignore",
        "proj/src/app.py",
    ]
    reasons = dict(d.skipped)
    r = ROOT.resolve()
    assert "default rules: .venv/" in reasons[str(r / "proj/.venv") + "/"]
    assert ".gitignore" in reasons[str(r / "proj/data") + "/"]
    assert "*.cache" in reasons[str(r / "proj/src/x.cache")]
    assert ".lakeignore" in reasons[str(r / "docs/private.md")]
    assert reasons[str(r / "docs/empty.txt")] == "empty file"


def test_decide_explains_paths_and_nested_ignores() -> None:
    d = DiskAdapter(RULES)
    assert d.decide(ROOT, ROOT / "docs/notes.md").reason == "indexed"
    assert d.decide(ROOT, ROOT / "proj/.venv/lib/x.py").ignored  # parent folder is ignored
    assert "default rules" in d.decide(ROOT, ROOT / "proj/.venv/lib/x.py").reason
    assert ".gitignore" in d.decide(ROOT, ROOT / "proj/data/dump.csv").reason


def test_size_cap_and_symlinks_skipped(tmp_path: Path) -> None:
    (tmp_path / "big.bin").write_bytes(b"x" * 100)
    (tmp_path / "ok.txt").write_text("ok")
    (tmp_path / "link.txt").symlink_to(tmp_path / "ok.txt")
    d = DiskAdapter("", max_bytes=10)
    assert [Path(i.path).name for i in d.scan(str(tmp_path))] == ["ok.txt"]
    assert {r for _, r in d.skipped} == {"symlink", "larger than 10 bytes"}
