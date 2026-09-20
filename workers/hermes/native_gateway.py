"""Launch the unmodified pinned Gateway with an explicit isolated profile."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["MIKASA_HERMES_SOURCE"])
if __name__ == "__main__":
    if Path.cwd() != Path(os.environ["HERMES_HOME"]) / "workspace":
        raise SystemExit("isolated workspace required")
    from hermes_cli.plugins import discover_plugins, get_plugin_manager
    discover_plugins()
    plugin = next((p for p in get_plugin_manager().list_plugins() if p["name"] == "mikasa"), {})
    if not plugin.get("enabled") or plugin.get("error") or plugin.get("hooks", 0) < 1:
        raise SystemExit("Mikasa policy plugin not active; refusing to start")
    from gateway.run import main
    main()
