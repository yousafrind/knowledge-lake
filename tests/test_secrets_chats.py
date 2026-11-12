import json
import zipfile
from pathlib import Path

import pytest
from lake_core.db import make_engine, upgrade_to_head
from lake_core.objectstore import ObjectStore, read_package
from lake_core.secrets import redact, scan
from lake_ingest.adapter import Item
from lake_ingest.chat import ChatGPTExportAdapter, ClaudeCodeAdapter, ClaudeExportAdapter
from lake_ingest.quarantine import held
from lake_ingest.registrar import Registrar
from lake_server.write_tools import save_conversation_json, save_document_json
from sqlalchemy import text

AWS = "AKIAIOSFODNN7EXAMPLE"
GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n-----END RSA PRIVATE KEY-----"


def test_scanner_finds_known_secret_shapes_and_skips_noise() -> None:
    body = f"key = {AWS}\ntoken {GH}\n{PEM}\npassword = 'xxxxxxxxxxxxxxxxxxxxxxxx'\napi_key: Zq8vN2mK9xLp4Rt7WcYe1HbU6"
    kinds = {f.kind for f in scan(body)}
    assert {"aws_access_key", "github_token", "private_key", "generic_secret"} <= kinds
    lines = {f.kind: f.line for f in scan(body)}
    assert lines["aws_access_key"] == 1 and lines["github_token"] == 2
    generic = [f for f in scan(body) if f.kind == "generic_secret"]
    assert len(generic) == 1  # the all-x password is low entropy, not a secret
    assert scan("just prose, a sha like 9f2c and the word password") == []


def test_redact_replaces_only_the_secret() -> None:
    body = f"use {AWS} here"
    assert redact(body, scan(body)) == "use [REDACTED:aws_access_key] here"


def test_secret_file_is_quarantined_then_released(db_url: str, store: ObjectStore) -> None:
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    reg = Registrar(eng, store)
    body = f"# Notes\n\nAWS key {AWS}"
    r = reg.register(Item(body.encode(), "/n.md", "disk", markdown=body))
    assert r.quarantined
    with eng.connect() as c:
        assert c.execute(text("select count(*) from job")).scalar_one() == 0
        assert c.execute(text("select count(*) from package")).scalar_one() == 0
        assert c.execute(text("select source_type from content")).scalar_one() == "quarantined"
    assert store.exists(f"quarantine/{r.content_sha256}")
    assert not store.exists(f"originals/{r.content_sha256[:2]}/{r.content_sha256}")
    assert [h.reasons for h in held(eng)] == [["aws_access_key"]]
    reg.release(r.content_sha256)
    with eng.connect() as c:
        assert c.execute(text("select processor from job")).scalar_one() == "chunk"
        assert c.execute(text("select source_type from content")).scalar_one() == "markdown"
    assert held(eng) == []
    with pytest.raises(ValueError):
        reg.release(r.content_sha256)


def test_claude_export(tmp_path: Path) -> None:
    data = [
        {
            "uuid": "u1",
            "name": "Plan",
            "created_at": "2026-01-02T03:04:05Z",
            "chat_messages": [
                {"sender": "human", "text": "hello"},
                {"sender": "assistant", "text": f"key {AWS}"},
            ],
        }
    ]
    z = tmp_path / "export.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("conversations.json", json.dumps(data))
    [item] = list(ClaudeExportAdapter().scan(str(z)))
    assert (
        item.path == "chat://claude/u1" and item.tier == "derived" and item.on_secrets == "redact"
    )
    assert item.markdown and item.markdown.startswith("# Plan\n\n## User\n\nhello\n\n## Assistant")


def test_chatgpt_export_follows_the_current_branch(tmp_path: Path) -> None:
    def node(role, text, parent, children=()):  # type: ignore[no-untyped-def]
        msg = {"author": {"role": role}, "content": {"parts": [text]}} if text else None
        return {"message": msg, "parent": parent, "children": list(children)}

    conv = {
        "title": "T",
        "create_time": 1_700_000_000,
        "conversation_id": "c1",
        "current_node": "a2",
        "mapping": {
            "root": node("system", "", None, ["u1"]),
            "u1": node("user", "q", "root", ["a1", "a2"]),
            "a1": node("assistant", "discarded draft", "u1"),
            "a2": node("assistant", "final", "u1"),
        },
    }
    (tmp_path / "conversations.json").write_text(json.dumps([conv]))
    [item] = list(ChatGPTExportAdapter().scan(str(tmp_path)))
    assert item.markdown and "final" in item.markdown and "discarded" not in item.markdown
    assert item.path == "chat://chatgpt/c1"


def test_claude_code_transcript(tmp_path: Path) -> None:
    lines = [
        {
            "type": "user",
            "message": {"role": "user", "content": "fix the bug"},
            "timestamp": "2026-02-01T00:00:00Z",
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "done"}, {"type": "tool_use"}],
            },
        },
        {"type": "summary"},
    ]
    p = tmp_path / "proj1" / "abcd1234.jsonl"
    p.parent.mkdir()
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    [item] = list(ClaudeCodeAdapter().scan(str(tmp_path)))
    assert item.markdown and "fix the bug" in item.markdown and "done" in item.markdown
    assert item.meta["project"] == "proj1"


def test_write_back_tools_redact_label_and_mark_derived(db_url: str, store: ObjectStore) -> None:
    upgrade_to_head(db_url)
    eng = make_engine(db_url)
    reg = Registrar(eng, store)
    out = json.loads(
        save_conversation_json(
            eng,
            reg,
            "Design chat",
            [{"role": "user", "content": "hi"}, {"role": "assistant", "content": f"use {GH}"}],
            tags=["design"],
            project="lake",
        )
    )
    assert out["status"] == "saved" and out["redacted"] == ["github_token"]
    sha = out["id"].removeprefix("lake://").split("#")[0]
    manifest, files = read_package(store, sha, 1)
    assert manifest["tier"] == "derived" and manifest["trust"] == "derived"
    assert b"ghp_" not in files["content.md"] and b"[REDACTED:github_token]" in files["content.md"]
    with eng.connect() as c:
        labels = {r.key: r.value for r in c.execute(text("select key, value from label"))}
        assert labels == {"tag:design": "1", "project": "lake"}
        assert c.execute(text("select tier from package")).scalar_one() == "derived"
    doc = json.loads(save_document_json(eng, reg, "Spec", "# Spec\n\nbody"))
    assert doc["status"] == "saved"
    with pytest.raises(ValueError):
        save_document_json(eng, reg, "", "x")
    with pytest.raises(ValueError):
        save_conversation_json(eng, reg, "t", [])
