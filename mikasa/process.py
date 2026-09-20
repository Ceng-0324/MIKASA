import os
import signal
import subprocess
import tempfile
import time

from .errors import MikasaError


def clean_env(extra=None):
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT") if k in os.environ}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "PYTHONDONTWRITEBYTECODE": "1"})
    if extra:
        env.update(extra)
    return env


def run(argv, *, cwd, timeout=120, limit=2_000_000, env=None, stdin=None, cancelled=None, pass_fds=(), decode_errors="replace"):
    """No shell, bounded disk-backed output, terminate the whole process group."""
    if not argv:
        raise MikasaError("执行命令尚未配置")
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as inp:
        if stdin:
            inp.write(stdin.encode())
        inp.seek(0)
        try:
            proc = subprocess.Popen(argv, cwd=cwd, env=env or clean_env(), stdin=inp,
                                    stdout=out, stderr=err, start_new_session=True, pass_fds=pass_fds)
        except OSError as exc:
            raise MikasaError("无法启动执行程序；检查 command 和安装路径") from exc
        deadline = time.monotonic() + timeout
        reason = None
        try:
            while proc.poll() is None:
                if cancelled and cancelled():
                    reason = "任务已取消或运行已暂停"
                elif time.monotonic() >= deadline:
                    reason = "执行超时"
                elif os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > limit:
                    reason = "执行输出超出上限"
                if reason:
                    break
                time.sleep(0.05)
        finally:
            # Kill leftover descendants even when the direct child exits normally.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        if reason:
            raise MikasaError(reason)
        if os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > limit:
            raise MikasaError("执行输出超出上限")
        out.seek(0)
        err.seek(0)
        return {"code": proc.returncode, "stdout": out.read(limit).decode("utf-8", decode_errors),
                "stderr": err.read(limit).decode("utf-8", decode_errors)}


def git(args, cwd, *, strip=True, **kwargs):
    result = run(["git", "--literal-pathspecs", "-c", "core.hooksPath=/dev/null", *args], cwd=cwd, **kwargs)
    if result["code"]:
        raise MikasaError("Git 操作失败：" + args[0] + "；检查仓库、ref 和访问权限")
    return result["stdout"].strip() if strip else result["stdout"]


def check_command(command, spec, workspace, timeout, cancelled):
    image = spec.get("check_image")
    if image:
        import uuid
        name = "mikasa-check-" + uuid.uuid4().hex
        argv = ["docker", "run", "--rm", "--pull=never", "--name", name,
                "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "--pids-limit=128", "--memory=1g", "--cpus=2", "--user", f"{os.getuid()}:{os.getgid()}",
                "--tmpfs", "/tmp:rw,nosuid,size=256m", "--mount", f"type=bind,source={workspace},target=/workspace",
                "--mount", f"type=bind,source={workspace}/.git,target=/workspace/.git,readonly",
                "--workdir=/workspace", "--env", "PYTHONDONTWRITEBYTECODE=1", image, *command]
        try:
            return run(argv, cwd=workspace, timeout=timeout, cancelled=cancelled)
        finally:
            # A terminated docker client alone does not stop the container.
            run(["docker", "rm", "-f", name], cwd=workspace, timeout=30)
    if spec.get("allow_local_checks") is not True:
        raise MikasaError("需要配置 check_image；仅受信任测试夹具可显式允许本机执行 checks")
    return run(command, cwd=workspace, timeout=timeout, cancelled=cancelled)
