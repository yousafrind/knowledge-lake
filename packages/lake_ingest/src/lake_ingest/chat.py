"""Chats as a source: export importers and the shared conversation renderer.

Export formats are written from knowledge of the current Claude.ai and ChatGPT account exports
and Claude Code session files; they were NOT checked against live exports (see build register).
"""

import json
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lake_core import ids

from lake_ingest.adapter import Item

LABELS = {"user": "User", "human": "User", "assistant": "Assistant", "system": "System"}


def render_conversation(title: str, messages: list[dict[str, str]]) -> str:
    parts = [f"# {title}"]
    for m in messages:
        who = LABELS.get(m.get("role", ""), m.get("role", "").title() or "Unknown")
        body = (m.get("content") or "").strip()
        if body:
            parts.append(f"## {who}\n\n{body}")
    return "\n\n".join(parts) + "\n"


def chat_item(
    origin: str,
    key: str,
    title: str,
    messages: list[dict[str, str]],
    when: datetime | None = None,
    meta: dict[str, object] | None = None,
) -> Item:
    md = render_conversation(title or "Untitled conversation", messages)
    return Item(
        md.encode(),
        f"chat://{origin}/{key}",
        "chat",
        when,
        source_type="chat",
        markdown=md,
        tier="derived",
        title=title or None,
        meta={"origin": origin, **(meta or {})},
        on_secrets="redact",
    )


def _read_json(path: Path, member: str) -> Any:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            return json.loads(z.read(member))
    target = path / member if path.is_dir() else path
    return json.loads(target.read_text())


def _ts(value: Any) -> datetime | None:
    try:
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value, UTC)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError, OSError):
        return None


class ClaudeExportAdapter:
    """Claude.ai data export: conversations.json (a list of conversations)."""

    name = "chat"

    def scan(self, root: str) -> Iterator[Item]:
        for conv in _read_json(Path(root), "conversations.json"):
            msgs = [
                {"role": m.get("sender", ""), "content": m.get("text", "")}
                for m in conv.get("chat_messages", [])
            ]
            yield chat_item(
                "claude", conv["uuid"], conv.get("name", ""), msgs, _ts(conv.get("created_at"))
            )


class ChatGPTExportAdapter:
    """ChatGPT data export: conversations.json with a message tree (`mapping`)."""

    name = "chat"

    def scan(self, root: str) -> Iterator[Item]:
        for conv in _read_json(Path(root), "conversations.json"):
            mapping = conv.get("mapping", {})
            chain: list[dict[str, Any]] = []
            node_id = conv.get("current_node")
            while node_id:  # walk from the last message up to the root, then reverse
                node = mapping.get(node_id) or {}
                if node.get("message"):
                    chain.append(node["message"])
                node_id = node.get("parent")
            msgs = []
            for m in reversed(chain):
                parts = (m.get("content") or {}).get("parts") or []
                text = "\n".join(p for p in parts if isinstance(p, str))
                role = (m.get("author") or {}).get("role", "")
                if role in ("user", "assistant") and text.strip():
                    msgs.append({"role": role, "content": text})
            key = (
                conv.get("conversation_id")
                or conv.get("id")
                or ids.content_sha256(json.dumps(msgs).encode())[:16]
            )
            yield chat_item(
                "chatgpt", key, conv.get("title", ""), msgs, _ts(conv.get("create_time"))
            )


class ClaudeCodeAdapter:
    """Claude Code session transcripts: ~/.claude/projects/<project>/<session>.jsonl"""

    name = "chat"

    def scan(self, root: str) -> Iterator[Item]:
        base = Path(root)
        files = [base] if base.is_file() else sorted(base.rglob("*.jsonl"))
        for f in files:
            msgs: list[dict[str, str]] = []
            first: Any = None
            for line in f.read_text(errors="replace").splitlines():
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") not in ("user", "assistant"):
                    continue
                first = first or rec.get("timestamp")
                content = (rec.get("message") or {}).get("content")
                if isinstance(content, list):
                    blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
                    content = "\n".join(b.get("text", "") for b in blocks)
                if isinstance(content, str) and content.strip():
                    msgs.append({"role": rec["type"], "content": content})
            if msgs:
                yield chat_item(
                    "claude-code",
                    f.stem,
                    f"Claude Code session {f.stem[:8]}",
                    msgs,
                    _ts(first),
                    {"project": f.parent.name},
                )
