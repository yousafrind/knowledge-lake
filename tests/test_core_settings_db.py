import re
from pathlib import Path

import pytest
from lake_core.db import make_engine, upgrade_to_head
from lake_core.settings import load_settings
from pydantic import ValidationError
from sqlalchemy import text

PACKAGES = Path(__file__).parent.parent / "packages"


def test_missing_required_settings_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for k in ("DATABASE_URL", "S3_ENDPOINT", "S3_KEY", "S3_SECRET"):
        monkeypatch.delenv(f"LAKE_{k}", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError):
        load_settings()


def test_env_overrides_toml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "lake.toml").write_text(
        'database_url="a"\ns3_endpoint="e"\ns3_key="k"\ns3_secret="s"\ns3_bucket="from-toml"\n'
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LAKE_DATABASE_URL", "from-env")
    s = load_settings()
    assert s.database_url == "from-env" and s.s3_bucket == "from-toml"


def test_fresh_db_upgrades_to_head(db_url: str) -> None:
    upgrade_to_head(db_url)
    with make_engine(db_url).connect() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar() == "0001"


def test_only_lake_core_reads_environment() -> None:
    pattern = re.compile(r"os\.environ|os\.getenv|\bgetenv\b")
    offenders = [
        str(p)
        for p in PACKAGES.rglob("*.py")
        if "lake_core" not in p.parts and pattern.search(p.read_text())
    ]
    assert not offenders
    # inside lake_core, only settings.py may read it
    inside = [
        p.name
        for p in (PACKAGES / "lake_core").rglob("*.py")
        if p.name != "settings.py" and pattern.search(p.read_text())
    ]
    assert not inside
