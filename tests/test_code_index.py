import subprocess
from pathlib import Path

import pytest
from lake_cli.main import main
from lake_code.symbols import extract_symbols
from lake_core.db import upgrade_to_head
from lake_core.objectstore import ObjectStore
from sqlalchemy import create_engine, text

PY = b'''"""Module doc."""
import os


class Repo:
    """Stores things."""

    def save(self, item, *, force=False):
        """Save one item."""
        return item


def helper(x):
    return x + 1
'''


def test_python_symbols_have_signature_doc_lines_and_parents() -> None:
    syms = {s.name: s for s in extract_symbols("python", PY)}
    assert set(syms) == {"Repo", "Repo.save", "helper"}
    assert syms["Repo.save"].kind == "method" and syms["Repo.save"].parent == "Repo"
    assert syms["Repo.save"].signature == "def save(self, item, *, force=False)"
    assert syms["Repo.save"].doc == "Save one item." and syms["Repo"].doc == "Stores things."
    assert (syms["helper"].start_line, syms["helper"].end_line) == (13, 14)


@pytest.mark.parametrize(
    ("lang", "src", "names"),
    [
        (
            "javascript",
            b"// adds\nfunction add(a, b) { return a + b }\nclass K { run() {} }\n",
            {"add", "K", "K.run"},
        ),
        (
            "typescript",
            b"interface Cfg { a: number }\nexport function f(x: Cfg): void {}\n",
            {"Cfg", "f"},
        ),
        ("go", b"package m\nfunc Add(a int) int { return a }\ntype T struct{}\n", {"Add", "T"}),
        ("rust", b"struct S;\nimpl S { fn go(&self) {} }\nfn main() {}\n", {"S", "S.go", "main"}),
        ("java", b"class A { void m() {} }\n", {"A", "A.m"}),
    ],
)
def test_other_languages(lang: str, src: bytes, names: set[str]) -> None:
    assert {s.name for s in extract_symbols(lang, src)} >= names


def test_javascript_doc_comment_attaches_to_function() -> None:
    syms = extract_symbols("javascript", b"// adds numbers\nfunction add(a, b) { return a + b }\n")
    assert syms[0].doc == "adds numbers"


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def test_lake_code_indexes_repo_respecting_gitignore(
    db_url: str, store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upgrade_to_head(db_url)
    for k, v in {
        "DATABASE_URL": db_url,
        "S3_ENDPOINT": store.s3.meta.endpoint_url,
        "S3_KEY": "k",
        "S3_SECRET": "s",
        "S3_BUCKET": store.bucket,
        "EMBEDDER": "hash",
    }.items():
        monkeypatch.setenv(f"LAKE_{k}", v)
    repo = tmp_path / "proj"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_bytes(PY)
    (repo / "README.md").write_text("# Proj\n\nA project.")
    (repo / "pyproject.toml").write_text('[project]\nname="proj"\ndependencies=["requests"]\n')
    (repo / ".env").write_text("SECRET=1")
    (repo / "ignored.py").write_text("def hidden(): pass")
    (repo / ".gitignore").write_text("ignored.py\n")
    git(repo, "init", "-q")
    git(repo, "-c", "user.email=a@b", "-c", "user.name=t", "add", ".")
    git(repo, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "init")
    main(["code", str(repo)])
    main(["work"])
    eng = create_engine(db_url)
    with eng.connect() as c:
        files = {r[0] for r in c.execute(text("select path from code_repo_file"))}
        assert files == {"src/app.py", "README.md", "pyproject.toml", ".gitignore"} - {".gitignore"}
        names = {r[0] for r in c.execute(text("select name from code_symbol"))}
        assert names == {"Repo", "Repo.save", "helper"}
        chunks = c.execute(
            text("select section from chunk where chunker_version='code-1' order by ordinal")
        ).all()
        assert [r[0] for r in chunks] == ["Repo", "Repo.save", "helper"]
        assert c.execute(text("select count(*) from embedding")).scalar_one() >= 3
        assert (
            c.execute(
                text("select count(*) from location where path like '%ignored.py'")
            ).scalar_one()
            == 0
        )
        assert (
            c.execute(text("select count(*) from location where path like '%.env'")).scalar_one()
            == 0
        )
