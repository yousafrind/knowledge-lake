"""Parser that sends the file to the burst GPU endpoint (workers/gpu) and returns its result."""

import httpx

from lake_parsers.base import Parsed


class RemoteParser:
    def __init__(self, url: str, name: str = "mineru", token: str | None = None) -> None:
        self.url, self.name, self.token = url.rstrip("/"), name, token
        self.version = "remote-1"

    def parse(self, data: bytes, filename: str) -> Parsed:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        r = httpx.post(
            f"{self.url}/parse",
            files={"file": (filename, data)},
            headers=headers,
            timeout=1800,
        )
        r.raise_for_status()
        body = r.json()
        return Parsed(markdown=body["markdown"], structure=body.get("structure", {}))
