"""Merge generated integration inputs without resetting Hermes-owned preferences."""
import json
import copy
import os
import re
import sys
from pathlib import Path


def merge(current, generated):
    current = copy.deepcopy(current)
    if "max_concurrent_sessions" in generated and current.get("_mikasa_native_tools") != 2:
        # Remove exact defaults installed by the former chat-only adapter. User-selected
        # toolsets and subsequent native changes survive refresh; the version bump repairs
        # profiles migrated by the earlier cleanup that missed the two-item default.
        previous_version = current.get("_mikasa_native_tools")
        toolsets = current.get("platform_toolsets", {})
        for platform in ("cli", "api_server", "feishu", "weixin"):
            legacy = [["memory", "skills"]]
            if previous_version != 1 or platform == "api_server":
                legacy.append(["memory", "skills", "session_search"])
            if toolsets.get(platform) in legacy:
                del toolsets[platform]
        gateway = current.get("gateway")
        api = gateway.get("api_server") if isinstance(gateway, dict) else None
        if isinstance(api, dict) and api.get("max_concurrent_runs") == 1:
            del api["max_concurrent_runs"]
            if not api:
                gateway.pop("api_server")
            if not gateway:
                current.pop("gateway")
        # Version 1 already completed the old default migration. Its later user
        # preferences must survive this repair; only unversioned profiles need
        # the original max-turn and display cleanup.
        if previous_version is None:
            agent = current.get("agent", {})
            if agent.get("max_turns") == 12:
                del agent["max_turns"]
            display = current.get("display", {})
            if display.get("tool_progress") == "off":
                display["tool_progress"] = "new"
        current["_mikasa_native_tools"] = 2
    # Hermes owns user preferences, including /model --global and reasoning.
    merged = {**generated, **current}
    # Add newly introduced display defaults to existing profiles, preserving
    # explicit choices (including False) and platform-specific preferences.
    merged["display"] = {**generated["display"], **current.get("display", {})}
    if "max_concurrent_sessions" in generated:
        merged["agent"] = {**generated["agent"], **current.get("agent", {})}
        merged["platforms"] = dict(current.get("platforms") or {})
        gateway = current.get("gateway") or {}
        for name, defaults in generated["platforms"].items():
            preferences = dict(merged["platforms"].get(name) or {})
            # Do not shadow native preferences written in another supported form.
            variants = [current.get(name) or {}, gateway.get(name) or {},
                        (gateway.get("platforms") or {}).get(name) or {}, preferences]
            for field, value in defaults.items():
                if not any(field in block or field in (block.get("extra") or {}) for block in variants):
                    preferences[field] = value
            merged["platforms"][name] = preferences
    # One-time migration from Mikasa's single-session, silent message defaults.
    # Afterwards /busy and native display/session preferences remain Hermes-owned.
    if "max_concurrent_sessions" in generated and current.get("_mikasa_interaction_defaults") != 1:
        for name in ("max_concurrent_sessions", "group_sessions_per_user", "thread_sessions_per_user", "streaming"):
            merged[name] = generated[name]
        display = {**current.get("display", {}), **generated["display"]}
        display.pop("busy_text_mode", None)  # old override would defeat /busy queue
        display["platforms"] = {**current.get("display", {}).get("platforms", {}),
                                **generated["display"]["platforms"]}
        merged["display"] = display
        merged["_mikasa_interaction_defaults"] = 1
    # Restore the former observable native defaults once. A profile marked 1 was
    # changed by Mikasa's quiet-progress migration; the explicit product choice to
    # restore per-tool visibility upgrades it to version 2. Later Hermes choices
    # remain untouched.
    if "max_concurrent_sessions" in generated and current.get("_mikasa_progress_defaults") != 2:
        if current.get("_mikasa_progress_defaults") == 1:
            if merged["display"].get("tool_progress") == "new":
                merged["display"]["tool_progress"] = "all"
            if merged["agent"].get("gateway_notify_interval") == 60:
                merged["agent"]["gateway_notify_interval"] = 15
        merged["_mikasa_progress_defaults"] = 2
    merged.pop("_mikasa_live_progress", None)
    # Bootstrap defaults must not reappear above an operator's nested Gateway choice.
    for name in ("max_concurrent_sessions", "group_sessions_per_user", "thread_sessions_per_user",
                 "streaming", "unauthorized_dm_behavior"):
        if name not in current and name in (current.get("gateway") or {}):
            merged.pop(name, None)
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
    if "platform_toolsets" in generated:
        merged["platform_toolsets"] = {**current.get("platform_toolsets", {}), **generated["platform_toolsets"]}
    for name, fields in (("skills", ("external_dirs", "auto_load")), ("plugins", ("enabled",))):
        merged[name] = {**generated[name], **current.get(name, {})}
        for field in fields:
            merged[name][field] = list(dict.fromkeys(generated[name][field] + current.get(name, {}).get(field, [])))
    # Track only the roots we own; a release update replaces them rather than
    # accumulating copies of mikasa-persona. Preserve arbitrary user roots.
    old_roots = current.get("_mikasa_skill_roots", [])
    new_roots = generated["skills"]["external_dirs"]
    def old_vm_root(value):
        return value == "/opt/mikasa/skills" or bool(re.fullmatch(
            r"/opt/mikasa-releases/(?:[a-f0-9]{40}|legacy-[0-9]+)/skills", value))
    merged["skills"]["external_dirs"] = list(dict.fromkeys(new_roots + [
        p for p in current.get("skills", {}).get("external_dirs", [])
        if p not in old_roots and not old_vm_root(p)]))
    merged["_mikasa_skill_roots"] = new_roots
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
