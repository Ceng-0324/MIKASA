"""Launch the pinned, unmodified Hermes interactive CLI in Mikasa's profile."""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["MIKASA_HERMES_SOURCE"])

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume")
    args = parser.parse_args()
    home = Path(os.environ["HERMES_HOME"])
    if Path.cwd() != home / "workspace":
        raise SystemExit("isolated workspace required")
    from hermes_cli.plugins import discover_plugins, get_plugin_manager
    discover_plugins()
    plugin = next((p for p in get_plugin_manager().list_plugins() if p["name"] == "mikasa"), {})
    if not plugin.get("enabled") or plugin.get("error"):
        raise SystemExit("Mikasa plugin failed to load")
    from agent.skill_commands import build_auto_load_prompt
    _, loaded, missing = build_auto_load_prompt(home_override=home)
    if "mikasa-persona" not in loaded or missing:
        raise SystemExit("Mikasa persona failed to load")
    from cli import main
    main(resume=args.resume)
