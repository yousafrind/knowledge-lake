import os
import subprocess
import sys
from pathlib import Path

from moto.server import ThreadedMotoServer

SCRIPT = Path(__file__).parent.parent / "deploy" / "local" / "check_stack.py"
DB = os.environ.get("LAKE_DATABASE_URL", "postgresql://lake:lake@localhost:5432/lake")


def test_check_stack_script() -> None:
    server = ThreadedMotoServer(port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    try:
        env = {
            **os.environ,
            "LAKE_DATABASE_URL": DB,
            "LAKE_S3_ENDPOINT": f"http://{host}:{port}",
            "LAKE_S3_KEY": "k",
            "LAKE_S3_SECRET": "s",
        }
        out = subprocess.run(
            [sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, check=False
        )
    finally:
        server.stop()
    assert out.returncode == 0, out.stderr
    assert "pgvector" in out.stdout and "bucket lake" in out.stdout
