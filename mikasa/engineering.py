"""Bind task execution to native account memory while keeping its workspace isolated."""
import fcntl
import json
import re
from contextlib import contextmanager

from .errors import Conflict, MikasaError
from .native import private_write, profile_home


@contextmanager
def engineering_profile(config, task, skills, terminal):
    actor = task['actor']  # Trusted task metadata, never payload/PR text or an owner fallback.
    account = profile_home(config, actor)
    task_id = task['id']
    if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', task_id):
        raise MikasaError('非法工程任务 ID')
    home = config.runtime / 'engineering' / task_id
    for path in (home.parent, home, home / 'workspace', account.parent, account, account / 'memories'):
        if path.is_symlink():
            raise MikasaError('工程 profile 或账号记忆目录不能为外部链接')
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = home / 'mikasa.lock'
    if lock_path.is_symlink():
        raise MikasaError('工程 profile 锁不能为链接')
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Conflict('该任务已有原生工程会话运行') from None
        binding = {'actor': actor, 'task_id': task_id, 'repo': task['payload']['repo']}
        marker = home / 'binding.json'
        if marker.is_symlink() or (marker.exists() and json.loads(marker.read_text()) != binding):
            raise MikasaError('工程 profile 的账号或仓库绑定不匹配')
        if (home / '.env').exists() or (home / '.env').is_symlink():
            raise MikasaError('原生工程 profile 不允许额外 .env 注入')
        target = account / 'memories'
        memory = home / 'memories'
        if memory.is_symlink():
            if memory.resolve() != target.resolve():
                raise MikasaError('工程记忆指向了其他账号或目录')
        elif memory.exists():
            archive = home / 'memories.legacy'
            if not memory.is_dir() or archive.exists() or archive.is_symlink():
                raise MikasaError('旧工程记忆归档冲突；原数据保留')
            memory.rename(archive)
        account.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.mkdir(exist_ok=True, mode=0o700)
        if not memory.is_symlink():
            memory.symlink_to(target, target_is_directory=True)
        private_write(marker, json.dumps(binding))
        (home / 'workspace').mkdir(exist_ok=True, mode=0o700)
        private_write(home / 'SOUL.md', (config.root / 'identity.md').read_text())
        native_config = {'terminal': terminal,
                         'skills': {'external_dirs': [str(config.root / 'skills')],
                                    'auto_load': [s['name'] for s in skills]},
                         'memory': {'memory_enabled': True, 'user_profile_enabled': True},
                         'plugins': {'enabled': []}}
        private_write(home / 'config.yaml', json.dumps(native_config))
        yield home
