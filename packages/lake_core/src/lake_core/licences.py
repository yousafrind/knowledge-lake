"""Licence check: flag installed packages whose licence is on the deny list (GPL family)."""

import re
from collections.abc import Iterable
from importlib.metadata import distributions

# GPL and AGPL, but not LGPL (linking is fine). Matches names and SPDX ids alike.
DENY = re.compile(r"(?<![A-Za-z])A?GPL|GNU (Affero )?General Public", re.I)
LGPL = re.compile(r"LGPL|Lesser General Public|Library General Public", re.I)


def installed() -> Iterable[tuple[str, list[str]]]:
    """(package name, every licence string it declares)."""
    for d in distributions():
        m = d.metadata
        found = [m.get("License-Expression") or "", m.get("License") or ""]
        found += [c for c in (m.get_all("Classifier") or []) if c.startswith("License ::")]
        yield m.get("Name") or "?", [f for f in found if f and len(f) < 200]


def violations(
    packages: Iterable[tuple[str, list[str]]], allowed: frozenset[str] = frozenset()
) -> list[tuple[str, str]]:
    bad = []
    for name, licences in packages:
        if name.lower() in allowed:
            continue
        for lic in licences:
            if DENY.search(lic) and not LGPL.search(lic):
                bad.append((name, lic))
                break
    return sorted(bad)
