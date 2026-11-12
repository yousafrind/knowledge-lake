import subprocess
import sys
from pathlib import Path

LINT = Path(sys.executable).parent / "lint-imports"
FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent


def run(config: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(LINT), "--config", config], cwd=cwd, capture_output=True, text=True, check=False
    )


def test_repo_obeys_layers() -> None:
    assert run(str(ROOT / "pyproject.toml"), ROOT).returncode == 0


def test_upward_import_fails() -> None:
    result = run(str(FIXTURES / "bad.ini"), FIXTURES)
    assert result.returncode != 0, result.stdout
