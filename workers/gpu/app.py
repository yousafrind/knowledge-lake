"""GPU parse endpoint wrapping MinerU. Runs on a rented GPU box; holds no database credentials.

UNVERIFIED: written without a GPU or model access. MinerU's Python API changes between
releases; adjust `run_mineru()` to the installed version before first use.
"""

import os
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile

app = FastAPI()
TOKEN = os.environ.get("GPU_TOKEN")


def run_mineru(pdf: Path, out: Path) -> str:
    # `mineru -p <input> -o <outdir>` writes <outdir>/<name>/auto/<name>.md in MinerU 2.x
    subprocess.run(["mineru", "-p", str(pdf), "-o", str(out)], check=True)
    return next(out.rglob("*.md")).read_text()


@app.post("/parse")
async def parse(file: UploadFile = File(...), authorization: str | None = Header(None)):  # type: ignore[no-untyped-def]
    if TOKEN and authorization != f"Bearer {TOKEN}":
        raise HTTPException(401)
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / Path(file.filename or "in.pdf").name
        src.write_bytes(await file.read())
        return {"markdown": run_mineru(src, Path(d) / "out"), "structure": {}}
