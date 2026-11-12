"""Read dependency lists from package manifests."""

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class Dependency:
    name: str
    spec: str
    ecosystem: str  # "python", "npm", "cargo", "go"
    dev: bool = False


REQ = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(\[[^\]]*\])?\s*(.*)$")


def _pep508(item: str) -> tuple[str, str]:
    m = REQ.match(item.split(";")[0])
    return (m.group(1), m.group(3).strip()) if m else (item, "")


def parse_manifest(path: str, content: str) -> list[Dependency]:
    name = PurePosixPath(path).name
    out: list[Dependency] = []
    if name == "pyproject.toml":
        doc = tomllib.loads(content)
        for item in doc.get("project", {}).get("dependencies", []):
            out.append(Dependency(*_pep508(item), "python"))
        for group in doc.get("dependency-groups", {}).values():
            out += [Dependency(*_pep508(i), "python", True) for i in group if isinstance(i, str)]
        for extra in doc.get("project", {}).get("optional-dependencies", {}).values():
            out += [Dependency(*_pep508(i), "python", True) for i in extra]
    elif name == "requirements.txt":
        for line in content.splitlines():
            line = line.split("#")[0].strip()
            if line and not line.startswith(("-", "git+", "http")):
                out.append(Dependency(*_pep508(line), "python"))
    elif name == "package.json":
        doc = json.loads(content)
        for key, dev in (("dependencies", False), ("devDependencies", True)):
            out += [Dependency(n, v, "npm", dev) for n, v in doc.get(key, {}).items()]
    elif name == "Cargo.toml":
        doc = tomllib.loads(content)
        for key, dev in (("dependencies", False), ("dev-dependencies", True)):
            for n, v in doc.get(key, {}).items():
                out.append(
                    Dependency(
                        n, v if isinstance(v, str) else str(v.get("version", "")), "cargo", dev
                    )
                )
    elif name == "go.mod":
        for m in re.finditer(
            r"^\s*(?:require\s+)?([\w.\-/]+\.[\w.\-/]+)\s+(v[\w.\-+]+)", content, re.M
        ):
            out.append(Dependency(m.group(1), m.group(2), "go"))
    return out


def search_terms(dep: Dependency) -> list[str]:
    """Words to look for in documentation titles and URLs."""
    base = dep.name.split("/")[-1] if dep.ecosystem in ("npm", "go") else dep.name
    base = base.lower().lstrip("@")
    return list(dict.fromkeys([base, base.replace("_", "-"), base.replace("-", "")]))
