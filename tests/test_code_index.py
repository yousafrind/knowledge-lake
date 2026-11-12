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


def test_references_and_imports() -> None:
    from lake_code.symbols import extract_references

    src = b"import os\nfrom a.b import c\n\ndef f(x):\n    y = helper(x)\n    return obj.save(y)\n"
    refs, imports = extract_references("python", src)
    by = {(r.name, r.kind) for r in refs}
    assert ("helper", "call") in by and ("save", "call") in by and ("obj", "ref") in by
    assert ("f", "ref") not in by  # a definition's own name is not a reference
    assert imports == ["import os", "from a.b import c"]


def test_code_tools(
    db_url: str, store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from lake_code import symbols  # noqa: F401
    from lake_core.embedding import HashEmbedder
    from lake_server import code_tools

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
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "core.py").write_bytes(PY)
    (repo / "pkg" / "cli.py").write_text(
        "from pkg.core import helper\n\n\ndef main():\n    return helper(2)\n"
    )
    git(repo, "init", "-q")
    git(repo, "-c", "user.email=a@b", "-c", "user.name=t", "add", ".")
    git(repo, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "init")
    main(["code", str(repo)])
    main(["work"])
    eng = create_engine(db_url)
    found = json.loads(code_tools.find_symbol_json(eng, "save"))["symbols"]
    assert found[0]["name"] == "Repo.save" and found[0]["path"] == "pkg/core.py"
    refs = json.loads(code_tools.find_references_json(eng, "helper"))["references"]
    assert {(r["path"], r["kind"]) for r in refs} == {("pkg/cli.py", "call"), ("pkg/cli.py", "ref")}
    outline = json.loads(code_tools.file_outline_json(eng, "pkg/core.py", "proj"))["symbols"]
    assert [s["name"] for s in outline] == ["Repo", "Repo.save", "helper"]
    got = json.loads(code_tools.get_file_json(eng, store, "pkg/core.py", 13, 14))
    assert got["text"].startswith("def helper") and got["total_lines"] == 14
    rmap = json.loads(code_tools.repo_map_json(eng, "proj"))["files"]
    assert rmap[0]["path"] == "proj/pkg/core.py" and rmap[0]["referenced_by_other_files"] >= 1
    hits = json.loads(code_tools.code_search_json(eng, HashEmbedder(), "helper"))
    assert hits["symbol_matches"][0]["name"] == "helper" and hits["results"]
    with pytest.raises(ValueError):
        code_tools.file_outline_json(eng, "nope.py")


def test_manifest_parsing() -> None:
    from lake_code.manifests import parse_manifest, search_terms

    py = parse_manifest(
        "pyproject.toml",
        '[project]\ndependencies=["requests>=2", "Pydantic-Core[x]==1; python_version>\'3\'"]\n'
        '[dependency-groups]\ndev=["pytest"]\n',
    )
    assert [(d.name, d.spec, d.dev) for d in py] == [
        ("requests", ">=2", False),
        ("Pydantic-Core", "==1", False),
        ("pytest", "", True),
    ]
    js = parse_manifest(
        "web/package.json", '{"dependencies":{"@scope/lib":"^1"},"devDependencies":{"jest":"29"}}'
    )
    assert [(d.name, d.dev) for d in js] == [("@scope/lib", False), ("jest", True)]
    assert search_terms(js[0])[0] == "lib"
    cargo = parse_manifest(
        "Cargo.toml",
        '[dependencies]\nserde = "1"\ntokio = { version = "1.2", features=["full"] }\n',
    )
    assert [(d.name, d.spec) for d in cargo] == [("serde", "1"), ("tokio", "1.2")]
    assert [d.name for d in parse_manifest("requirements.txt", "flask==3\n# c\n-e .\n")] == [
        "flask"
    ]
    gomod = parse_manifest(
        "go.mod", "module x\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.0\n)\n"
    )
    assert gomod[0].name == "github.com/gin-gonic/gin" and search_terms(gomod[0])[0] == "gin"


def test_dependency_docs_link_to_crawled_documentation(
    db_url: str, store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from lake_core.db import make_engine
    from lake_ingest.adapter import Item
    from lake_ingest.registrar import Registrar
    from lake_server import code_tools

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
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname="proj"\ndependencies=["requests>=2","rare-lib"]\n'
    )
    (repo / "app.py").write_text("import requests\n")
    git(repo, "init", "-q")
    git(repo, "-c", "user.email=a@b", "-c", "user.name=t", "add", ".")
    git(repo, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "i")
    eng = make_engine(db_url)
    md = "# Requests: HTTP for Humans\n\nQuickstart."
    Registrar(eng, store).register(
        Item(
            md.encode(),
            "https://docs.example.org/requests/quickstart.html",
            "crawl",
            source_type="html",
            markdown=md,
        )
    )
    main(["code", str(repo)])
    main(["work"])
    deps = {
        d["dependency"]: d
        for d in json.loads(code_tools.dependency_docs_json(eng, store))["dependencies"]
    }
    assert deps["requests"]["docs"][0]["title"].startswith("Requests")
    assert deps["requests"]["docs"][0]["location"].endswith("quickstart.html")
    assert deps["rare-lib"]["docs"] == []
