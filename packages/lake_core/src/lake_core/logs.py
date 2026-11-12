"""Structured JSON logs. Job lines carry `job_id` and `content_sha256`."""

import json
import logging

FIELDS = ("job_id", "content_sha256", "processor", "outcome", "attempts", "error")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        line.update({k: v for k in FIELDS if (v := getattr(record, k, None)) is not None})
        return json.dumps(line)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
