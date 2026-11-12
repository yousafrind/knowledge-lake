import re


def title_from_markdown(md: str, fallback: str) -> str:
    """First top-level heading, else the fallback (usually the file name without suffix)."""
    m = re.search(r"^#\s+(.*\S)\s*$", md, re.M)
    return m.group(1) if m else fallback
