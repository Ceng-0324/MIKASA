"""Platform configuration and explicit, non-publishing connection checks."""
import json
import fcntl
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from .errors import Conflict, MikasaError
from .maintenance import runtime_operation


def validate_weixin_binding(value, owner):
    """The QR-confirming account is the sole trusted chat principal."""
    if not isinstance(value, dict) or value.get("actor") != owner:
        raise MikasaError("微信绑定不属于当前负责人；请重新执行 weixin-login")
    for field in ("account_id", "user_id"):
        if not isinstance(value.get(field), str) or not re.fullmatch(r"[A-Za-z0-9_@.-]{1,200}", value[field]) or value[field] in {".", ".."}:
            raise MikasaError("微信扫码未返回有效账号和用户标识；原绑定保留")
    if not isinstance(value.get("token"), str) or not value["token"].strip():
        raise MikasaError("微信扫码未返回凭据；原绑定保留")
    url = urlparse(value.get("base_url", ""))
    if (url.scheme != "https" or not url.hostname or not url.hostname.endswith(".weixin.qq.com") or
            url.username or url.password or url.port not in (None, 443) or url.query or url.fragment or url.path not in ("", "/")):
        raise MikasaError("微信服务地址不是预期的腾讯 HTTPS 端点；原绑定保留")
    return value


def weixin_binding(config):
    path = config.runtime / "credentials/weixin.json"
    try:
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise MikasaError("微信凭据必须为独立的 0600 文件")
        return validate_weixin_binding(json.loads(path.read_text()), config.owner)
    except (OSError, ValueError, TypeError):
        raise MikasaError("微信尚未绑定或凭据无法读取；先运行 weixin-login") from None


@runtime_operation
def login_weixin(config):
    from .native import native_installation
    source, python = native_installation(config)
    directory = config.runtime / "credentials"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = directory / "weixin.lock"
    if lock_path.is_symlink():
        raise MikasaError("微信登录锁不能为符号链接")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Conflict("微信扫码登录正在进行") from None
        # QR login is model-independent and cannot mutate the running owner's profile.
        with tempfile.TemporaryDirectory(prefix="mikasa-weixin-login-") as temporary:
            env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "SSL_CERT_FILE") if k in os.environ}
            env.update(HERMES_HOME=temporary, MIKASA_HERMES_SOURCE=str(source),
                       HERMES_ENABLE_PROJECT_PLUGINS="0", PYTHONUNBUFFERED="1")
            try:
                return subprocess.run([str(python), str(config.root / "workers/hermes/weixin_login.py"),
                                       str(directory / "weixin.json"), config.owner],
                                      cwd=temporary, env=env, timeout=540).returncode
            except subprocess.TimeoutExpired:
                raise MikasaError("微信扫码超时；原绑定保留，请重试") from None


def weixin_diagnostics(config):
    try:
        weixin_binding(config)
    except MikasaError as exc:
        return {"platform": "weixin", "configuration": "incomplete", "connection": "not_checked",
                "owner_bound": False, "error": str(exc)}
    return {"platform": "weixin", "configuration": "ready", "connection": "not_checked",
            "owner_bound": True, "transport": "long_poll", "messages": "not_checked"}


def feishu_environment(config):
    settings = config.data.get("feishu", {})
    return {
        "FEISHU_APP_ID": config.secret("feishu", "app_id_env", "MIKASA_FEISHU_APP_ID"),
        "FEISHU_APP_SECRET": config.secret("feishu", "app_secret_env", "MIKASA_FEISHU_APP_SECRET"),
        "FEISHU_DOMAIN": settings.get("domain", "feishu"),
        "FEISHU_CONNECTION_MODE": "websocket", "FEISHU_ALLOWED_USERS": "",
        "FEISHU_ALLOW_ALL_USERS": "true", "FEISHU_GROUP_POLICY": "open",
        "FEISHU_ALLOW_BOTS": "all", "FEISHU_REQUIRE_MENTION": "false",
        # The platform opt-in opens Feishu without opening other Gateway adapters.
        "GATEWAY_ALLOW_ALL_USERS": "false",
        "GATEWAY_MULTIPLEX_PROFILES": "false",
    }


def messaging_gateway(config, platforms):
    """Supply credentials and native configuration; Hermes owns all message routing."""
    if not platforms or set(platforms) - {"feishu", "weixin"}:
        raise MikasaError("请选择 feishu 或 weixin 消息平台")
    env = {"GATEWAY_ALLOW_ALL_USERS": "false", "GATEWAY_MULTIPLEX_PROFILES": "false"}
    settings = {"platforms": {}, "unauthorized_dm_behavior": "ignore", "multiplex_profiles": False,
                "stt_enabled": False, "max_concurrent_sessions": 1, "streaming": {"enabled": False}}
    for platform in dict.fromkeys(platforms):
        if platform == "feishu":
            env.update(feishu_environment(config))
            extra = {"app_id": env["FEISHU_APP_ID"], "default_group_policy": "open",
                     "allow_bots": "all", "require_mention": False}
        else:
            binding = weixin_binding(config)
            env.update(WEIXIN_TOKEN=binding["token"], WEIXIN_ALLOW_ALL_USERS="false",
                       WEIXIN_ALLOWED_USERS=binding["user_id"])
            extra = {"account_id": binding["account_id"], "base_url": binding["base_url"],
                     "dm_policy": "allowlist", "allow_from": [binding["user_id"]],
                     "group_policy": "disabled", "group_allow_from": []}
        settings["platforms"][platform] = {"enabled": True, "gateway_restart_notification": False,
                                           "typing_indicator": False, "extra": extra}
    return env, settings


def diagnostics(config, platform, *, probe=False):
    if platform == "weixin":
        if probe:
            raise MikasaError("微信认证需扫码，收发由 Gateway 验收；不以消费消息的长轮询充当只读探针")
        return weixin_diagnostics(config)
    settings = config.data.get(platform, {})
    fields = {"token_env": "MIKASA_GITHUB_TOKEN"} if platform == "github" else {
        "app_id_env": "MIKASA_FEISHU_APP_ID", "app_secret_env": "MIKASA_FEISHU_APP_SECRET"}
    required = [settings.get(field, default) for field, default in fields.items()]
    missing = [name for name in required if not os.environ.get(name)]
    ready = not missing
    result = {"platform": platform, "configuration": "ready" if ready else "incomplete",
              "missing_environment": missing, "connection": "not_checked"}
    if platform == "github":
        result.update(account=config.bot, repositories=list(config.data.get("repositories", {})),
                      write_access="not_checked", webhook="not_checked")
    else:
        result.update(owner_bound=bool(settings.get("owner_open_id")), domain=settings.get("domain", "feishu"),
                      transport="websocket", messages="not_checked", owner_identity="not_checked",
                      access={"users": "all", "groups": "open", "bots": "all", "require_mention": False})
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
