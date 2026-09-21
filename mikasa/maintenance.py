"""Cross-process exclusion between runtime activity and offline snapshots."""
import fcntl
from contextlib import contextmanager
from functools import wraps

from .errors import Conflict, MikasaError


@contextmanager
def runtime_lock(runtime, *, exclusive=False):
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = runtime / 'maintenance.lock'
    if path.is_symlink():
        raise MikasaError('维护锁不能为符号链接')
    with path.open('a') as lock:
        try:
            fcntl.flock(lock, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Conflict('运行状态正在使用或备份；停止相关进程后重试') from None
        yield


def runtime_operation(function):
    @wraps(function)
    def wrapped(owner, *args, **kwargs):
        config = getattr(owner, 'config', owner)
        with runtime_lock(config.runtime):
            return function(owner, *args, **kwargs)
    return wrapped
