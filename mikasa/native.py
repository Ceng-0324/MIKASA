"""Isolated native Hermes CLI/Gateway lifecycle; no agent loop or transcript replication."""
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import tempfile
from pathlib import Path

from .errors import Conflict, MikasaError
from .model_settings import default_model, model_choices, model_environment, select_source, validate_environment
from .maintenance import runtime_operation

HERMES_REVISION = "f9524d3f119c672e4a4444f56d582e7475716ba3"


def private_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise MikasaError("原生 profile 文件不能为符号链接")
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        stream.write(content)
    temporary.replace(path)
    path.chmod(0o600)


def provider_id(source):
    return "cch-" + hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()[:16]


def profile_home(config, actor, *, engineering=False):
    config.authorize(actor)
    return config.runtime / ("engineer" if engineering else "native") / hashlib.sha256(actor.encode()).hexdigest()[:24]


def verify_source(source):
    if (source / ".git").exists():
        revision = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, check=True).stdout.strip()
    else:
        # Offline archives carry provenance from the earlier Git-blob verification.
        # Never accidentally inspect the enclosing Mikasa repository as Hermes.
        marker = source / ".mikasa-source.json"
        provenance = json.loads(marker.read_text()) if marker.is_file() else {}
        revision = provenance.get("revision") if provenance.get("repository") == "NousResearch/hermes-agent" else None
        dirty = not provenance.get("verified_git_blobs")
    if revision != HERMES_REVISION or dirty or (source / ".env").exists():
        raise MikasaError("原生 Hermes 必须使用固定且未修改的源码，无额外 .env 注入")


def native_installation(config):
    """Locate and verify Hermes without preparing a model or touching a profile."""
    settings = config.data.get("worker", {})
    source = (config.root / settings.get("hermes_source", "runtime/cache/hermes-source")).resolve()
    python = Path(settings.get("native_python", config.root / "runtime/cache/hermes-venv/bin/python"))
    if not python.is_absolute():
        python = config.root / python
    if not python.is_file() or not (source / "gateway/run.py").is_file():
        raise MikasaError("缺少原生 Hermes 源码或 Python 环境")
    verify_source(source)
    return source, python


def runtime_environment(config, home, source, python, credentials):
    """Use the Linux account and explicitly supplied tool credentials in every entry."""
    env = {k: os.environ[k] for k in ("HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL", "TMPDIR",
                                     "TERM", "COLORTERM", "SSL_CERT_FILE") if k in os.environ}
    for section in ("worker", "engineering"):
        env.update({k: os.environ[k] for k in config.data.get(section, {}).get("env_allowlist", []) if k in os.environ})
    env["PATH"] = str(python.parent) + os.pathsep + env.get("PATH", os.defpath)
    token = os.environ.get(config.data.get("github", {}).get("token_env", "MIKASA_GITHUB_TOKEN"))
    if token:
        env["GH_TOKEN"] = token
    env.update(credentials, HERMES_HOME=str(home), MIKASA_HERMES_SOURCE=str(source), PYTHONUNBUFFERED="1")
    return env


@runtime_operation
def prepare_profile(config, actor, *, engineering=False):
    """Regenerate immutable inputs only. Never overwrite native memories or sessions."""
    home = profile_home(config, actor, engineering=engineering)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings = config.data.get("worker", {})
    source, python = native_installation(config)
    actor_identity = {"actor": actor, "engineering": engineering}
    binding_path = config.runtime / "credentials/weixin.json"
    if binding_path.exists() or binding_path.is_symlink():
        from .connections import weixin_binding
        binding = weixin_binding(config)
        actor_identity["weixin_owner"] = {"account": config.owner, "user_id": binding["user_id"]}
    model = default_model(config)
    sources = [(settings.get("model_source", {"type": "environment"}), model)]
    for route in settings.get("model_routes", []):
        # Resolve credentials with an explicit model, including Claude Code alias configurations.
        sources.append((route["model_source"], next(iter(route.get("models", [])), model)))
    providers, credentials = {}, {}
    for selection, representative in sources:
        name = provider_id(selection)
        if name in providers:
            continue
        values = validate_environment(model_environment({**settings, "model_source": selection, "model_routes": []}, representative), required=True)
        variable = "MIKASA_CCH_" + name[4:].upper()
        credentials[variable] = values["MIKASA_MODEL_API_KEY"]
        providers[name] = {"base_url": values["MIKASA_MODEL_BASE_URL"], "key_env": variable,
                           "api_mode": values.get("MIKASA_MODEL_API_MODE", "chat_completions")}
    choices = sorted({model, *model_choices(settings)})
    for name, provider in providers.items():
        provider["models"] = {m: {} for m in choices if provider_id(select_source(settings, m)) == name}
    native_config = {
        "model": {"default": model, "provider": provider_id(select_source(settings, model))},
        "providers": providers,
        "model_aliases": {m: {"model": m, "provider": provider_id(select_source(settings, m))} for m in choices},
        "memory": {"memory_enabled": True, "user_profile_enabled": True},
        "skills": {"external_dirs": [str(config.root / "skills")], "auto_load": ["mikasa-persona"]},
        "plugins": {"enabled": ["mikasa"]},
        "agent": {"gateway_notify_interval": 15},
        "terminal": {"backend": "local", "cwd": str(home / "workspace")},
        "max_concurrent_sessions": None,
        "group_sessions_per_user": False,
        "thread_sessions_per_user": False,
        "unauthorized_dm_behavior": "ignore",
        "platforms": {name: {"gateway_restart_notification": False} for name in ("feishu", "weixin")},
        "streaming": {"enabled": True},
        "display": {"language": "zh", "busy_input_mode": "queue", "busy_ack_detail": False,
                    "tool_progress": "all",
                    "interim_assistant_messages": True, "background_process_notifications": "error",
                    "long_running_notifications": True, "show_reasoning": False,
                    "platforms": {"weixin": {"streaming": False, "long_running_notifications": True}}},
    }
    if engineering:
        # Native CLI/Gateway toolsets, budgets, backends and extensions stay native.
        for name in ("platform_toolsets", "agent", "gateway", "max_concurrent_sessions",
                     "group_sessions_per_user", "thread_sessions_per_user", "streaming", "fallback_providers",
                     "platforms", "unauthorized_dm_behavior"):
            native_config.pop(name, None)
        native_config["terminal"] = {"backend": "local"}
        native_config["display"] = {"language": "zh"}
        native_config["skills"]["auto_load"].append("mikasa-engineering")
        account = profile_home(config, actor)
        target = account / "memories"
        for path in (account, target, home / "memories"):
            if path.is_symlink() and (path != home / "memories" or path.resolve() != target.resolve()):
                raise MikasaError("工程记忆绑定与账号不匹配；原数据保留")
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        memory = home / "memories"
        if not memory.is_symlink():
            if memory.exists():
                raise MikasaError("工程记忆目录已存在且未绑定；原数据保留")
            memory.symlink_to(target, target_is_directory=True)
    (home / "workspace").mkdir(exist_ok=True, mode=0o700)
    refreshed = subprocess.run([str(python), str(config.root / "workers/hermes/profile_config.py"), str(home / "config.yaml"),
                                *( ["--engineering"] if engineering else [])],
                               input=json.dumps(native_config), capture_output=True, text=True, timeout=30,
                               env={k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TMPDIR") if k in os.environ})
    if refreshed.returncode:
        raise MikasaError("原生配置更新失败；原有配置保留，请检查配置结构与所选 CCH provider")
    private_write(home / "SOUL.md", (config.root / "identity.md").read_text())
    # Snapshots are generated from the canonical files, never maintained separately.
    for name in ("engineering-contract.md", "engineering-workflow.md"):
        private_write(home / "policy" / name, (config.root / name).read_text())
    # On-demand native skill generated from canonical rules; never a second maintained copy.
    private_write(home / "skills/mikasa-engineering/SKILL.md",
                  "---\nname: mikasa-engineering\ndescription: Load Mikasa's canonical engineering contract and workflow for substantive engineering decisions.\n---\n\n" +
                  "\n\n".join((config.root / name).read_text() for name in
                                ("engineering-contract.md", "engineering-workflow.md")))
    feishu = config.data.get("feishu", {})
    owner_ids = [feishu[key] for key in ("owner_open_id", "owner_user_id") if feishu.get(key)]
    actor_identity["feishu_owner"] = {"account": config.owner, "ids": owner_ids}
    private_write(home / "policy/actor.json", json.dumps(actor_identity, ensure_ascii=False))
    plugin = config.root / "workers/hermes/plugin"
    for name in ("plugin.yaml", "__init__.py"):
        private_write(home / "plugins/mikasa" / name, (plugin / name).read_text())
    return home, source, python, credentials


@runtime_operation
def interactive(config, session=None, *, platforms=()):
    """Foreground native CLI or messaging Gateway; Hermes owns interaction."""
    platform_env = {}
    if platforms:
        from .connections import messaging_gateway
        platform_env, settings = messaging_gateway(config, platforms)
        if session:
            raise MikasaError("消息平台会话由 Hermes Gateway 管理")
    actor = config.owner
    home = profile_home(config, actor)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (home / "mikasa.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Conflict("该账号的原生 profile 正在初始化；稍后重试") from None
        home, source, python, credentials = prepare_profile(config, actor)
    # The profile lock protects only bootstrap. Hermes owns concurrent sessions
    # and the Gateway runtime lock once its child process has started.
    env = runtime_environment(config, home, source, python, credentials)
    env.update(platform_env)
    command = [str(python), str(config.root / "workers/hermes/native_cli.py")]
    gateway_tmp = None
    previous = None
    process = None
    try:
        if platforms:
            gateway_tmp = tempfile.TemporaryDirectory(prefix=".mikasa-gateway-", dir=home)
            gateway_config = Path(gateway_tmp.name) / "config.json"
            private_write(gateway_config, json.dumps(settings))
            command = [str(python), str(config.root / "workers/hermes/native_gateway.py"), "--config", str(gateway_config)]
        if session:
            command += ["--resume", session]
        def terminate(signum, frame):
            raise SystemExit(128 + signum)

        previous = signal.signal(signal.SIGTERM, terminate)
        process = subprocess.Popen(command, cwd=home / "workspace", env=env)
        return process.wait()
    except KeyboardInterrupt:
        # The foreground process group already received Ctrl-C; Hermes handles it.
        if process is None:
            raise
        return process.wait()
    finally:
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        finally:
            if previous is not None:
                signal.signal(signal.SIGTERM, previous)
            if gateway_tmp is not None:
                gateway_tmp.cleanup()
