"""Consistent task/receipt snapshots; native account homes need a full backup."""
import fcntl
import json
import sqlite3
from pathlib import Path

from .errors import Conflict, MikasaError


def backup_tasks(service, destination):
    target = Path(destination).resolve()
    if target.exists():
        raise MikasaError('备份目标已存在，拒绝覆盖')
    service.tasks.call('prepare')  # Migration must acquire the runner lock itself.
    with (service.config.runtime / 'runner.lock').open('a') as runner:
        try:
            fcntl.flock(runner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Conflict('任务运行中；结束后再创建任务备份') from None
        with (service.tasks.home / 'adapter.lock').open('a') as adapter:
            fcntl.flock(adapter, fcntl.LOCK_EX)
            target.mkdir(parents=True, mode=0o700)
            (target / 'kanban').mkdir(mode=0o700)
            for source, relative in ((service.store.path, 'mikasa.sqlite3'),
                                     (service.tasks.path, 'kanban/kanban.db')):
                output = target / relative
                with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(output) as dst:
                    src.backup(dst)
                output.chmod(0o600)
            manifest = {'version': 1, 'scope': 'tasks-and-receipts',
                        'files': ['mikasa.sqlite3', 'kanban/kanban.db'],
                        'excluded': ['native', 'engineering', 'scheduler', 'workspaces', 'credentials']}
            marker = target / 'manifest.json'
            marker.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
            marker.chmod(0o600)
    return {'backup': str(target), **manifest}
