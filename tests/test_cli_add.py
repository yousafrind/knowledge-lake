from pathlib import Path

import pytest
from lake_cli.main import main
from lake_core.db import upgrade_to_head
from lake_core.objectstore import ObjectStore


@pytest.fixture
def env(db_url: str, store: ObjectStore, monkeypatch: pytest.MonkeyPatch) -> None:
    upgrade_to_head(db_url)
    monkeypatch.setenv("LAKE_DATABASE_URL", db_url)
    monkeypatch.setenv("LAKE_S3_ENDPOINT", store.s3.meta.endpoint_url)
    monkeypatch.setenv("LAKE_S3_KEY", "k")
    monkeypatch.setenv("LAKE_S3_SECRET", "s")
    monkeypatch.setenv("LAKE_S3_BUCKET", store.bucket)


def test_add_folder_twice_reports_no_new_content(
    env: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.md").write_text("# A")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.pdf").write_bytes(b"%PDF-fake")
    main(["add", str(tmp_path)])
    assert "2 files, 2 new content, 2 new locations" in capsys.readouterr().out
    main(["add", str(tmp_path)])
    assert "2 files, 0 new content, 0 new locations" in capsys.readouterr().out


def test_add_single_file_end_to_end(
    env: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "x.txt"
    f.write_text("hello")
    main(["add", str(f)])
    assert "1 files, 1 new content" in capsys.readouterr().out
