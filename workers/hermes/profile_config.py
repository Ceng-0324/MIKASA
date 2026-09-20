"""Merge generated integration inputs without resetting Hermes-owned preferences."""
import json
import os
import re
import sys
from pathlib import Path


def merge(current, generated):
    # Hermes owns user preferences, including /model --global and reasoning.
    merged = {**generated, **current}
    # cch-<source digest> is Mikasa's namespace; removed sources must not linger
    # in the native picker. Keep unrelated native providers and aliases intact.
    managed = lambda name: isinstance(name, str) and re.fullmatch(r"cch-[0-9a-f]{16}", name)
    selected = merged["model"].get("provider")
    if managed(selected) and selected not in generated["providers"]:
        raise ValueError("selected CCH provider was removed; choose a configured provider")
    merged["providers"] = {**{k: v for k, v in current.get("providers", {}).items() if not managed(k)},
                           **generated["providers"]}
    merged["model_aliases"] = {
        **{k: v for k, v in current.get("model_aliases", {}).items()
           if not (isinstance(v, dict) and managed(v.get("provider")))},
        **generated["model_aliases"],
    }
    merged["platform_toolsets"] = {**current.get("platform_toolsets", {}), **generated["platform_toolsets"]}
    for name, fields in (("skills", ("external_dirs", "auto_load")), ("plugins", ("enabled",))):
        merged[name] = {**generated[name], **current.get(name, {})}
        for field in fields:
            merged[name][field] = list(dict.fromkeys(generated[name][field] + current.get(name, {}).get(field, [])))
    return merged


def main():
    path = Path(sys.argv[1])
    if path.is_symlink():
        raise ValueError("profile config cannot be a symlink")
    current = {}
    if path.exists():
        text = path.read_text()
        try:
            current = json.loads(text)
        except ValueError:
            # Use the pinned Hermes interpreter's YAML dependency, not the host Python.
            import yaml
            current = yaml.safe_load(text)
        if not isinstance(current, dict):
            raise ValueError("profile config must be a mapping")
    generated = json.load(sys.stdin)
    content = json.dumps(merge(current, generated), ensure_ascii=False, indent=2)
    temp = path.with_name(path.name + ".tmp")
    if temp.is_symlink():
        raise ValueError("profile temporary config cannot be a symlink")
    with open(temp, "w", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        stream.write(content)
    temp.replace(path)
    path.chmod(0o600)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Invalid local YAML may contain secrets; never reflect parser diagnostics.
        raise SystemExit("Unable to refresh native profile configuration") from None
