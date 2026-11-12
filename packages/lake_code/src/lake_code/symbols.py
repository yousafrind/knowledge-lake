"""Symbol extraction with tree-sitter: definitions with signature, docstring and line range."""

from dataclasses import dataclass
from functools import cache
from typing import Any

from tree_sitter import Language, Node, Parser

# node types that define a symbol, per language -> kind
DEFS: dict[str, dict[str, str]] = {
    "python": {"function_definition": "function", "class_definition": "class"},
    "javascript": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "generator_function_declaration": "function",
    },
    "typescript": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "enum_declaration": "enum",
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_spec": "type",
    },
    "rust": {
        "function_item": "function",
        "struct_item": "struct",
        "enum_item": "enum",
        "trait_item": "trait",
        "impl_item": "impl",
    },
    "java": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "method_declaration": "method",
        "enum_declaration": "enum",
    },
}
DEFS["tsx"] = DEFS["typescript"]
CONTAINERS = {"class", "interface", "impl", "trait", "struct", "enum"}


@dataclass(frozen=True)
class Symbol:
    name: str  # qualified, e.g. "Repo.save"
    kind: str
    signature: str
    doc: str
    start_line: int  # 1-based, inclusive
    end_line: int
    parent: str | None


@cache
def _parser(language: str) -> Parser:
    import tree_sitter_go as go
    import tree_sitter_java as java
    import tree_sitter_javascript as js
    import tree_sitter_python as py
    import tree_sitter_rust as rs
    import tree_sitter_typescript as ts

    langs: dict[str, Any] = {
        "python": py.language,
        "javascript": js.language,
        "typescript": ts.language_typescript,
        "tsx": ts.language_tsx,
        "go": go.language,
        "rust": rs.language,
        "java": java.language,
    }
    return Parser(Language(langs[language]()))


def _name(node: Node, kind: str) -> str | None:
    n = node.child_by_field_name("name") or (
        node.child_by_field_name("type") if kind == "impl" else None
    )
    return n.text.decode(errors="replace") if n and n.text else None


def _signature(node: Node, source: bytes) -> str:
    body = node.child_by_field_name("body")
    end = body.start_byte if body else node.end_byte
    text = source[node.start_byte : end].decode(errors="replace")
    return " ".join(text.split())[:300].rstrip(" :{")


def _doc(node: Node, source: bytes, language: str) -> str:
    if language == "python":
        body = node.child_by_field_name("body")
        first = body.children[0] if body and body.children else None
        if first is not None and first.type == "expression_statement" and first.children:
            lit = first.children[0]
            if lit.type == "string" and lit.text:
                return lit.text.decode(errors="replace").strip("\"' \n")
        return ""
    prev = node.prev_named_sibling
    lines: list[str] = []
    while (
        prev is not None
        and "comment" in prev.type
        and prev.end_point[0] >= node.start_point[0] - 1 - len(lines)
    ):
        lines.insert(0, (prev.text or b"").decode(errors="replace").strip("/* \n"))
        prev = prev.prev_named_sibling
    return "\n".join(lines)


def extract_symbols(language: str, source: bytes) -> list[Symbol]:
    defs = DEFS[language]
    out: list[Symbol] = []

    def visit(node: Node, parent: str | None) -> None:
        kind = defs.get(node.type)
        name = _name(node, kind) if kind else None
        current = parent
        if kind and name:
            qualified = f"{parent}.{name}" if parent else name
            if kind == "function" and parent:
                kind = "method"
            out.append(
                Symbol(
                    qualified,
                    kind,
                    _signature(node, source),
                    _doc(node, source, language),
                    node.start_point[0] + 1,
                    node.end_point[0] + 1,
                    parent,
                )
            )
            if kind in CONTAINERS:
                current = qualified
        for child in node.children:
            visit(child, current)

    visit(_parser(language).parse(source).root_node, None)
    return out


IDENTIFIERS = {
    "identifier",
    "property_identifier",
    "type_identifier",
    "field_identifier",
    "shorthand_property_identifier",
}
CALLS = {"call", "call_expression", "method_invocation"}
MEMBERS = {"attribute", "member_expression", "selector_expression", "field_expression"}
IMPORTS = {
    "import_statement",
    "import_from_statement",
    "import_declaration",
    "use_declaration",
    "import_spec",
}


@dataclass(frozen=True)
class Reference:
    name: str
    line: int
    kind: str  # "call" or "ref"


def extract_references(language: str, source: bytes) -> tuple[list[Reference], list[str]]:
    """Name-based references and imports (heuristic: no scope or type resolution)."""
    refs: set[Reference] = set()
    imports: list[str] = []

    def is_call(node: Node) -> bool:
        parent = node.parent
        if parent is None:
            return False
        if parent.type in CALLS:
            return (
                parent.child_by_field_name("function") == node
                or parent.child_by_field_name("name") == node
            )
        if parent.type in MEMBERS and parent.parent is not None and parent.parent.type in CALLS:
            member = parent.child_by_field_name("attribute") or parent.child_by_field_name(
                "property"
            )
            member = member or parent.child_by_field_name("field")
            return member == node and parent.parent.child_by_field_name("function") == parent
        return False

    def visit(node: Node) -> None:
        if node.type in IMPORTS:
            imports.append(" ".join((node.text or b"").decode(errors="replace").split())[:200])
        if node.type in IDENTIFIERS and node.text:
            parent = node.parent
            is_def = (
                parent is not None
                and parent.child_by_field_name("name") == node
                and (parent.type in DEFS[language])
            )
            if not is_def:
                refs.add(
                    Reference(
                        node.text.decode(errors="replace"),
                        node.start_point[0] + 1,
                        "call" if is_call(node) else "ref",
                    )
                )
        for child in node.children:
            visit(child)

    visit(_parser(language).parse(source).root_node)
    return sorted(refs, key=lambda r: (r.line, r.name)), imports
