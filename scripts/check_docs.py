#!/usr/bin/env python3
"""Read-only documentation checks, including files not yet tracked by Git."""
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
errors = []
excluded = {".git", ".venv", "__pycache__", "installed", "local", "state", "workspaces", "cache", "home", "backups"}
for path in root.rglob("*.md"):
    if set(path.relative_to(root).parts) & excluded:
        continue
    text = path.read_text()
    for number, line in enumerate(text.splitlines(), 1):
        if line.endswith("\t") or (line.endswith(" ") and not line.endswith("  ")):
            errors.append(f"{path.relative_to(root)}:{number}: trailing whitespace")
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if "://" not in target and not target.startswith("#"):
            if not (path.parent / target.split("#")[0]).exists():
                errors.append(f"{path.relative_to(root)}: missing link {target}")
entry = (root / "AGENTS.md").read_text()
try:
    assert entry.index("1. [identity.md]") < entry.index("2. [engineering-contract.md]") < entry.index("3. [engineering-workflow.md]")
except (ValueError, AssertionError):
    errors.append("canonical read order changed")
if errors:
    raise SystemExit("\n".join(errors))
print("Documentation links, whitespace and canonical read order: OK")
