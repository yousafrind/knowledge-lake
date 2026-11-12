# Docs

- `plan.md`, `architecture.md`, `build-order.md` are markdown exports of the Claude Docs originals.
- Sync: re-export, overwrite the file, commit as `docs: sync <name> (rev N)`. `git log -p docs/<name>.md` shows how the project evolved.
- Diagrams are not in the markdown export; architecture.md marks each with a `Diagram:` line.
- History before the first commit is not in git.
- Work tracking: `work/items.csv` is canonical; `build-order.md` is a readable copy. Decision changes go in `adr/`.
