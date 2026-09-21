"""Platform configuration and explicit, non-publishing connection checks."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

from .errors import MikasaError


def feishu_environment(config):
    settings = config.data.get("feishu", {})
    owner = settings.get("owner_open_id")
    if not owner:
        raise MikasaError("先配置 feishu.owner_open_id，绑定负责人在该应用中的身份")
    return {
        "FEISHU_APP_ID": config.secret("feishu", "app_id_env", "MIKASA_FEISHU_APP_ID"),
        "FEISHU_APP_SECRET": config.secret("feishu", "app_secret_env", "MIKASA_FEISHU_APP_SECRET"),
        "FEISHU_DOMAIN": settings.get("domain", "feishu"),
        "FEISHU_CONNECTION_MODE": "websocket", "FEISHU_ALLOWED_USERS": ",".join(
            value for value in (owner, settings.get("owner_user_id")) if value),
        "FEISHU_ALLOW_ALL_USERS": "false", "FEISHU_GROUP_POLICY": "disabled",
        "FEISHU_ALLOW_BOTS": "none", "GATEWAY_ALLOW_ALL_USERS": "false",
        "GATEWAY_MULTIPLEX_PROFILES": "false",
    }


def feishu_gateway_config(app_id):
    return {"platforms": {"feishu": {"enabled": True, "gateway_restart_notification": False,
                                     "typing_indicator": False, "extra": {"app_id": app_id}}},
            "unauthorized_dm_behavior": "ignore", "multiplex_profiles": False,
            "stt_enabled": False, "max_concurrent_sessions": 1,
            "streaming": {"enabled": False}}


def diagnostics(config, platform, *, probe=False):
    settings = config.data.get(platform, {})
    fields = {"token_env": "MIKASA_GITHUB_TOKEN"} if platform == "github" else {
        "app_id_env": "MIKASA_FEISHU_APP_ID", "app_secret_env": "MIKASA_FEISHU_APP_SECRET"}
    required = [settings.get(field, default) for field, default in fields.items()]
    missing = [name for name in required if not os.environ.get(name)]
    ready = not missing
    if platform == "feishu":
        ready = ready and bool(settings.get("owner_open_id"))
    result = {"platform": platform, "configuration": "ready" if ready else "incomplete",
              "missing_environment": missing, "connection": "not_checked"}
    if platform == "github":
        result.update(account=config.bot, repositories=list(config.data.get("repositories", {})),
                      write_access="not_checked", webhook="not_checked")
    else:
        result.update(owner_bound=bool(settings.get("owner_open_id")), domain=settings.get("domain", "feishu"),
                      transport="websocket", messages="not_checked", owner_identity="not_checked")
    if probe:
        if missing:
            raise MikasaError("缺少接入凭据环境变量：" + ", ".join(missing))
        if platform == "github":
            from .github import GitHub
            result.update(GitHub(config).probe())
        else:
            result.update(probe_feishu(config))
    return result


def probe_feishu(config):
    from .native import verify_source
    credentials = feishu_environment(config)
    settings = config.data.get("worker", {})
    source = (config.root / settings.get("hermes_source", "runtime/cache/hermes-source")).resolve()
    python = Path(settings.get("native_python", config.root / "runtime/cache/hermes-venv/bin/python"))
    if not python.is_absolute():
        python = config.root / python
    if not python.is_file():
        raise MikasaError("飞书探针需要固定 Hermes Python 环境")
    verify_source(source)
    with tempfile.TemporaryDirectory(prefix="mikasa-feishu-probe-") as temporary:
        env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "SSL_CERT_FILE") if k in os.environ}
        env.update(credentials, HERMES_HOME=temporary, MIKASA_HERMES_SOURCE=str(source),
                   HERMES_ENABLE_PROJECT_PLUGINS="0")
        try:
            reply = subprocess.run([str(python), str(config.root / "workers/hermes/feishu_probe.py")],
                                   cwd=temporary, env=env, capture_output=True, text=True, timeout=45)
            value = json.loads(reply.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise MikasaError("飞书认证探针失败或超时；检查网络和固定 SDK 环境") from None
        if reply.returncode or value != {"connection": "passed", "bot_identity": "passed"}:
            raise MikasaError("飞书认证探针未通过；检查应用凭据、domain 和机器人能力")
        return value
