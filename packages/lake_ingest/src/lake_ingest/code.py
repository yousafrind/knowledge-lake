"""Code adapter: a git repo (or plain folder) -> code files + manifests + markdown docs."""

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from lake_core import ids
from lake_core.languages import language_of
from sqlalchemy import Engine, text

from lake_ingest.adapter import Item
from lake_ingest.disk import DiskAdapter

MANIFESTS = {
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
}
NEVER = (".env", ".pem", ".key", "id_rsa", "id_ed25519", ".p12", ".pfx")  # full scan: W-027
MAX_BYTES = 2 * 1024 * 1024


@dataclass
class RepoInfo:
    root: str
    commit: str
    files: dict[str, str] = field(default_factory=dict)  # relative path -> content sha


def _git(root: Path, *args: str) -> str | None:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    return r.stdout if r.returncode == 0 else None


def wanted(rel: str) -> bool:
    name = Path(rel).name
    if name.startswith(NEVER[0]) or name.endswith(NEVER) or name.startswith(NEVER[3:5]):
        return False
    return bool(language_of(rel)) or name in MANIFESTS or rel.lower().endswith(".md")


class CodeAdapter:
    name = "code"

    def __init__(self, default_rules: str = "") -> None:
        self.default_rules = default_rules
        self.repo: RepoInfo | None = None

    def _list(self, root: Path) -> list[Path]:
        out = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        if out is not None:  # git decides: tracked + untracked-but-not-ignored
            return [root / rel for rel in out.split("\0") if rel]
        walker = DiskAdapter(self.default_rules)  # no git: use the disk ignore rules
        return [Path(i.path) for i in walker.scan(str(root))]

    def scan(self, root: str) -> Iterator[Item]:
        base = Path(root).resolve()
        top = _git(base, "rev-parse", "--show-toplevel")
        if top:
            base = Path(top.strip())
        commit = (_git(base, "rev-parse", "HEAD") or "").strip() or "WORKTREE"
        self.repo = RepoInfo(str(base), commit)
        for p in sorted(self._list(base)):
            rel = p.relative_to(base).as_posix()
            if not p.is_file() or p.is_symlink() or not wanted(rel) or p.stat().st_size > MAX_BYTES:
                continue
            data = p.read_bytes()
            self.repo.files[rel] = ids.content_sha256(data)
            is_code = bool(language_of(rel))
            md = None if is_code else data.decode("utf-8", errors="replace")
            yield Item(
                data,
                str(p),
                self.name,
                datetime.fromtimestamp(p.stat().st_mtime, UTC),
                source_type="code"
                if is_code
                else ("manifest" if Path(rel).name in MANIFESTS else None),
                markdown=md,
            )


def record_repo(engine: Engine, repo: RepoInfo) -> int:
    with engine.begin() as c:
        rid = c.execute(
            text(
                "insert into code_repo(root,name) values (:r,:n) "
                "on conflict (root) do update set name=excluded.name returning id"
            ),
            {"r": repo.root, "n": Path(repo.root).name},
        ).scalar_one()
        for rel, sha in repo.files.items():
            c.execute(
                text(
                    "insert into code_repo_file(repo_id,commit_sha,path,content_sha) "
                    "values (:r,:c,:p,:s) on conflict do nothing"
                ),
                {"r": rid, "c": repo.commit, "p": rel, "s": sha},
            )
    return int(rid)
