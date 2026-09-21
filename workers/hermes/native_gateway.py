"""Launch the unmodified pinned Gateway with an explicit isolated profile."""
import os
import sys
import json
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
    from agent.skill_commands import build_auto_load_prompt
    _, loaded, missing = build_auto_load_prompt(home_override=Path(os.environ["HERMES_HOME"]))
    if "mikasa-persona" not in loaded or missing:
        raise SystemExit("Required persona skill not loaded; refusing to start")
    if "--config" in sys.argv:
        # Explicit messaging startup must not silently become a cron-only process.
        from gateway.config import GatewayConfig
        from gateway.platform_registry import platform_registry
        path = Path(sys.argv[sys.argv.index("--config") + 1])
        config = GatewayConfig.from_dict(json.loads(path.read_text()))
        for platform, settings in config.platforms.items():
            entry = platform_registry.get(platform.value)
            if settings.enabled and (entry is None or not entry.check_fn() or
                    (entry.validate_config is not None and not entry.validate_config(settings))):
                raise SystemExit("Messaging platform prerequisites missing; install the pinned dependency snapshot and check platform config")
    from gateway.run import main
    main()
