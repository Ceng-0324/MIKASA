"""Launch the unmodified pinned Gateway with an explicit isolated profile."""
import os
import sys
import json
import asyncio
from pathlib import Path

sys.path.insert(0, os.environ["MIKASA_HERMES_SOURCE"])


def messaging_config(path):
    from gateway.config import Platform, PlatformConfig, load_gateway_config
    config = load_gateway_config()
    explicit = json.loads(path.read_text())
    # Hermes resolves YAML, nested gateway settings, env, home channels and
    # platform preferences. Only bind the explicitly requested messaging accounts.
    platforms = {}
    for name, requested in explicit["platforms"].items():
        platform = Platform(name)
        settings = config.platforms.get(platform, PlatformConfig())
        settings.enabled = True
        settings.extra.update(requested.get("extra", {}))
        platforms[platform] = settings
    config.platforms = platforms
    return config


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
        from gateway.config import Platform
        from gateway.platform_registry import platform_registry
        from gateway.run import _instantiate_builtin_adapter, start_gateway, _exit_after_graceful_shutdown
        path = Path(sys.argv[sys.argv.index("--config") + 1])
        config = messaging_config(path)
        for platform, settings in config.platforms.items():
            if not settings.enabled:
                continue
            # Explicit config skips Hermes' env loader. Keep bot tokens in process
            # memory, so neither generated config nor state backups acquire them.
            if platform == Platform.WEIXIN:
                settings.token = os.environ.get("WEIXIN_TOKEN")
                if not settings.token or not settings.extra.get("account_id"):
                    raise SystemExit("Messaging platform prerequisites missing: Weixin binding")
            entry = platform_registry.get(platform.value)
            available = (entry.check_fn() and (entry.validate_config is None or entry.validate_config(settings))
                         if entry else _instantiate_builtin_adapter(platform, settings) is not None)
            if not available:
                raise SystemExit("Messaging platform prerequisites missing; install the pinned dependency snapshot and check platform config")
        # Native lifecycle includes all platforms, locks, dispatch, retries and shutdown.
        # Use its programmatic entry so the in-memory token need not be serialized.
        try:
            success = asyncio.run(start_gateway(config))
            code = 0 if success else 1
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 0 if exc.code is None else 1
        _exit_after_graceful_shutdown(code)
    else:
        from gateway.run import main
        main()
