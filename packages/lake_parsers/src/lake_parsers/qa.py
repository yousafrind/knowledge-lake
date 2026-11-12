"""Cheap, deterministic parse-quality checks. A failure triggers escalation to a stronger parser."""

from typing import Any

from lake_parsers.base import Parsed

MIN_CHARS_PER_KB = 20  # a 1 MB scan that yields almost no text probably failed OCR
MAX_BAD_RATIO = 0.02  # share of replacement / control characters


def score(parsed: Parsed, source_bytes: int, source_type: str) -> dict[str, Any]:
    text = parsed.markdown
    reasons: list[str] = []
    n = len(text.strip())
    if n == 0:
        reasons.append("empty")
    elif source_type in ("pdf", "docx", "epub") and source_bytes > 20_000:
        if n / (source_bytes / 1024) < MIN_CHARS_PER_KB:
            reasons.append("too little text for the file size")
    bad = sum(1 for ch in text if ch == "�" or (ord(ch) < 32 and ch not in "\n\r\t"))
    ratio = bad / n if n else 0.0
    if ratio > MAX_BAD_RATIO:
        reasons.append("garbled characters")
    return {"ok": not reasons, "reasons": reasons, "chars": n, "bad_ratio": round(ratio, 4)}
