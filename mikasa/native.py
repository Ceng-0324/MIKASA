"""Isolated native Hermes CLI/Gateway lifecycle; no agent loop or transcript replication."""
import fcntl
import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler

from .errors import Conflict, MikasaError
from .model_settings import default_model, model_choices, model_environment, select_source, validate_environment
from .run_events import RunEvents, TERMINAL
from .maintenance import runtime_lock, runtime_operation

HERMES_REVISION = "f9524d3f119c672e4a4444f56d582e7475716ba3"


class NativeAPIError(MikasaError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Hermes 原生 API 请求失败（HTTP {status}）")


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
        "terminal": {"backend": "local", "cwd": str(home / "workspace")},
        "max_concurrent_sessions": None,
        "group_sessions_per_user": False,
        "thread_sessions_per_user": False,
        "streaming": {"enabled": True},
        "display": {"language": "zh", "busy_input_mode": "queue", "busy_ack_detail": False,
                    "tool_progress": "new", "interim_assistant_messages": True,
                    "long_running_notifications": True, "show_reasoning": False,
                    "platforms": {"weixin": {"streaming": False, "long_running_notifications": True}}},
    }
    if engineering:
        # Native CLI/Gateway toolsets, budgets, backends and extensions stay native.
        for name in ("platform_toolsets", "agent", "gateway", "max_concurrent_sessions",
                     "group_sessions_per_user", "thread_sessions_per_user", "streaming", "fallback_providers"):
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
    key_path = home / ".api-key"
    if not key_path.exists():
        private_write(key_path, secrets.token_urlsafe(48))
    if key_path.is_symlink() or key_path.stat().st_mode & 0o077:
        raise MikasaError("原生 API 本机凭据必须为独立的 0600 文件")
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
            raise Conflict("该账号的原生 profile 正在使用；先关闭对应 CLI 或 Gateway") from None
        home, source, python, credentials = prepare_profile(config, actor)
        env = runtime_environment(config, home, source, python, credentials)
        env.update(platform_env)
        # Import only existing legacy state; starting native CLI needs no Mikasa database.
        database = config.runtime / "mikasa.sqlite3"
        if database.exists():
            imported = subprocess.run([str(python), str(config.root / "workers/hermes/import_legacy.py"), str(database), actor],
                                      cwd=home / "workspace", env=env, capture_output=True, timeout=60)
            if imported.returncode:
                raise MikasaError("旧会话导入失败；原数据库保留，CLI 未启动")
        command = [str(python), str(config.root / "workers/hermes/native_cli.py")]
        if platforms:
            gateway_config = home / "gateway-messaging.json"
            private_write(gateway_config, json.dumps(settings))
            command = [str(python), str(config.root / "workers/hermes/native_gateway.py"), "--config", str(gateway_config)]
        if session:
            command += ["--resume", session]
        def terminate(signum, frame):
            raise SystemExit(128 + signum)

        previous = signal.signal(signal.SIGTERM, terminate)
        process = None
        try:
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
                signal.signal(signal.SIGTERM, previous)


class NativeGateway:
    def __init__(self, config, actor):
        config.authorize(actor)
        self.config, self.actor = config, actor
        self.process = None
        self._lock = None
        self._maintenance = runtime_lock(config.runtime)
        self._maintenance.__enter__()
        try:
            self.home = profile_home(config, actor)
            self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._lock = (self.home / "mikasa.lock").open("a")
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            home, source, python, credentials = prepare_profile(config, actor)
            self.key = (home / ".api-key").read_text()
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            self.url = f"http://127.0.0.1:{port}"
            self.http = build_opener(ProxyHandler({}))
            env = runtime_environment(config, home, source, python, credentials)
            env.update(API_SERVER_KEY=self.key, API_SERVER_HOST="127.0.0.1", API_SERVER_PORT=str(port))
            with open(home / "gateway.log", "a", opener=lambda p, f: os.open(p, f, 0o600)) as log:
                imported = subprocess.run([str(python), str(config.root / "workers/hermes/import_legacy.py"),
                                           str(config.runtime / "mikasa.sqlite3"), actor],
                                          cwd=home / "workspace", env=env, stdin=subprocess.DEVNULL,
                                          stdout=log, stderr=log, timeout=60)
                if imported.returncode:
                    raise MikasaError("旧聊天导入未通过；原始 SQLite 保留，原生 Gateway 未启动")
                self.process = subprocess.Popen([str(python), str(config.root / "workers/hermes/native_gateway.py")],
                                                cwd=home / "workspace", env=env, stdin=subprocess.DEVNULL,
                                                stdout=log, stderr=log, start_new_session=True)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise MikasaError("原生 Hermes Gateway 启动失败；检查隔离 home 的 gateway.log")
                try:
                    self.request("GET", "/v1/capabilities")
                    return
                except MikasaError:
                    time.sleep(.2)
            raise MikasaError("原生 Hermes Gateway 启动超时")
        except BlockingIOError:
            self.close()
            raise Conflict("该账号的原生 Gateway 已由其他 Mikasa 进程管理") from None
        except BaseException:
            self.close()
            raise

    def request(self, method, path, body=None, key=None):
        headers = {"Authorization": "Bearer " + self.key, "Content-Type": "application/json"}
        if key:
            headers["Idempotency-Key"] = key
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        try:
            with self.http.open(Request(self.url + path, data=data, headers=headers, method=method), timeout=10) as response:
                return json.load(response)
        except HTTPError as exc:
            # Do not reflect upstream response text, which can contain credentials or prompts.
            exc.close()
            raise NativeAPIError(exc.code) from None
        except (URLError, OSError, ValueError):
            raise MikasaError("Hermes 原生 API 不可用") from None

    def selection(self, model):
        return {"model": model, "provider": provider_id(select_source(self.config.data.get("worker", {}), model))}

    def create(self, session, model):
        return self.request("POST", "/api/sessions", {"id": session, **self.selection(model), "require_model_lock": True})

    def set_model(self, session, model):
        session = self.messages(session)["session_id"]
        return self.request("POST", f"/api/sessions/{session}/model",
                            {**self.selection(model), "require_model_lock": True})

    def ensure_session(self, session, model):
        try:
            return self.create(session, model)
        except NativeAPIError as exc:
            if exc.status != 409:
                raise
            return self.session(session)

    def session(self, session):
        live_id = self.messages(session)["session_id"]
        return self.request("GET", "/api/sessions/" + live_id)["session"]

    def messages(self, session):
        return self.request("GET", f"/api/sessions/{session}/messages")

    def start(self, session, message, model, key):
        # Hermes loads its own full persisted history, including compression rotations.
        return self.request("POST", "/v1/runs", {"session_id": session, "input": message, **self.selection(model)}, key)

    def wait(self, run_id, cancelled=lambda: False):
        deadline = time.monotonic() + self.config.data.get("worker", {}).get("timeout", 600)
        path = '/v1/runs/' + run_id

        def read_status(cancel_requested=False):
            status = self.request('GET', path)
            if cancel_requested or cancelled():
                if status['status'] not in TERMINAL:
                    self.request('POST', path + '/stop', {})
                raise MikasaError("运行已暂停；原生历史与请求回执保留")
            if status["status"] in {"failed", "cancelled", "interrupted"}:
                raise MikasaError("Hermes 原生运行失败或已中止；历史保留，未重新发起请求")
            return status

        def check_stop():
            cancel_requested = cancelled()
            if cancel_requested or time.monotonic() >= deadline:
                status = read_status(cancel_requested)  # A just-completed run needs no stop.
                if status['status'] != 'completed':
                    self.request('POST', path + '/stop', {})
                    raise MikasaError('原生运行已请求取消；后续请检查会话记录')
                return status

        status = read_status()  # Receipts can already be terminal, even after restart.
        if status['status'] != 'completed':
            with RunEvents(self.url, self.key, run_id) as events:
                while not events.done.wait(.1):
                    completed = check_stop()
                    if completed is not None:
                        status = completed
                        break
                else:
                    if events.http_status in {401, 403}:
                        raise NativeAPIError(events.http_status)
                    status = read_status()
            # Pinned Hermes retires the transport on disconnect. There is no
            # Last-Event-ID replay: recover this same run's durable state only.
            while status['status'] != 'completed':
                until = min(deadline, time.monotonic() + 1)
                while time.monotonic() < until:
                    completed = check_stop()
                    if completed is not None:
                        status = completed
                        break
                    time.sleep(.1)
                if status['status'] == 'completed':
                    break
                completed = check_stop()
                status = completed if completed is not None else read_status()
        evidence_path = self.home / 'request-evidence' / (hashlib.sha256(run_id.encode()).hexdigest() + '.json')
        if evidence_path.exists():
            evidence = json.loads(evidence_path.read_text())
            status.setdefault('runtime', {}).update({k: evidence[k] for k in
                ('api_mode', 'reported_model', 'identity', 'policy', 'skills_index', 'persona_skill') if k in evidence})
        return status

    def close(self):
        if self.process and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=5)
        if self._lock:
            self._lock.close()
            self._lock = None
        if getattr(self, '_maintenance', None):
            self._maintenance.__exit__(None, None, None)
            self._maintenance = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class NativeGateways:
    """Owned by the HTTP server or CLI, not a process-global agent registry."""
    def __init__(self, config):
        self.config, self.instances = config, {}
        self.lock = threading.Lock()
        self.closed = False

    def for_actor(self, actor):
        self.config.authorize(actor)
        with self.lock:
            if self.closed:
                raise MikasaError("原生 Gateway 管理器已关闭")
            previous = self.instances.get(actor)
            if previous is not None and previous.process.poll() is not None:
                previous.close()
                del self.instances[actor]
            if actor not in self.instances:
                self.instances[actor] = NativeGateway(self.config, actor)
            return self.instances[actor]

    def close(self):
        with self.lock:
            self.closed = True
            for instance in self.instances.values():
                instance.close()
            self.instances.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
