"""Regex secret scanner. Findings never contain the secret itself, only kind and line."""

import math
import re
from collections import Counter
from dataclasses import dataclass

PATTERNS: dict[str, re.Pattern[str]] = {
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{50,}\b"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "private_key": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY(?: BLOCK)?-----"
        r"(?:.*?-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----)?",
        re.S,
    ),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "stripe_key": re.compile(r"\b[sr]k_live_[0-9A-Za-z]{20,}\b"),
    "llm_api_key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{32,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
}
ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|secret|token|passwd|password|access[_-]?key)\b\s*[:=]\s*"
    r"['\"]?([A-Za-z0-9/+_\-]{20,})['\"]?"
)


@dataclass(frozen=True)
class Finding:
    kind: str
    line: int
    start: int
    end: int


def _entropy(s: str) -> float:
    counts = Counter(s)
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def scan(text: str) -> list[Finding]:
    found: list[Finding] = []
    for kind, pat in PATTERNS.items():
        for m in pat.finditer(text):
            found.append(Finding(kind, text.count("\n", 0, m.start()) + 1, m.start(), m.end()))
    for m in ASSIGNMENT.finditer(text):
        if _entropy(m.group(1)) >= 3.5:  # skips values like "xxxxxxxxxxxxxxxxxxxx" or "changeme..."
            found.append(
                Finding("generic_secret", text.count("\n", 0, m.start(1)) + 1, m.start(1), m.end(1))
            )
    return sorted(found, key=lambda f: f.start)


def redact(text: str, findings: list[Finding]) -> str:
    out, pos = [], 0
    for f in findings:
        if f.start < pos:  # overlapping match already covered
            continue
        out += [text[pos : f.start], f"[REDACTED:{f.kind}]"]
        pos = f.end
    out.append(text[pos:])
    return "".join(out)
