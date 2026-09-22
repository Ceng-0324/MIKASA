"""Bootstrap Mikasa's engineering identity, then hand control to the native Hermes CLI."""
import fcntl
import os
import signal
import subprocess
from pathlib import Path

from .errors import MikasaError
from .maintenance import runtime_operation
from .native import prepare_profile, profile_home


@runtime_operation
def launch(config, arguments=(), *, cwd=None):
    home = profile_home(config, config.owner, engineering=True)
    if home.is_symlink():
        raise MikasaError("工程 profile 不能为外部链接")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Only bootstrap is serialized. Native sessions/dispatcher own run concurrency.
    with (home / 'mikasa.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        home, source, python, credentials = prepare_profile(config, config.owner, engineering=True)
    settings = config.data.get('engineering', {})
    workspace = Path(cwd or settings.get('cwd') or home / 'workspace').expanduser().resolve()
    if not workspace.is_dir():
        raise MikasaError('工程工作目录不存在；先准备仓库或工作目录')
    env = {k: os.environ[k] for k in ('HOME', 'USER', 'LOGNAME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'TERM', 'COLORTERM', 'SSL_CERT_FILE')
           if k in os.environ}
    env.update({k: os.environ[k] for k in settings.get('env_allowlist', []) if k in os.environ})
    env['PATH'] = str(python.parent) + os.pathsep + env.get('PATH', os.defpath)
    # Native credential resolution receives the account token; terminal scrubbing remains upstream-owned.
    token = os.environ.get(config.data.get('github', {}).get('token_env', 'MIKASA_GITHUB_TOKEN'))
    if token:
        env['GH_TOKEN'] = token
    env.update(credentials, HERMES_HOME=str(home), MIKASA_HERMES_SOURCE=str(source), PYTHONUNBUFFERED='1')
    argv = list(arguments)
    if argv[:1] == ['--']:
        argv.pop(0)
    command = [str(python), str(config.root / 'workers/hermes/native_engineer.py'), *argv]

    def terminate(signum, frame):
        raise SystemExit(128 + signum)

    previous = signal.signal(signal.SIGTERM, terminate)
    child = None
    try:
        child = subprocess.Popen(command, cwd=workspace, env=env)
        return child.wait()
    except KeyboardInterrupt:
        if child is None:
            raise
        return child.wait()
    finally:
        try:
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        finally:
            signal.signal(signal.SIGTERM, previous)
