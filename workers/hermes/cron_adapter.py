"""Private, credential-free Cron home; all scheduling uses the pinned native SDK."""
import fcntl
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, os.environ['MIKASA_HERMES_SOURCE'])
from cron import jobs
from cron.scheduler import tick
from mikasa.errors import Conflict, MikasaError
from mikasa.native import private_write

SCRIPT = 'mikasa-audit.py'
CONFIG_PAUSE = 'mikasa:configuration'


def reconcile(request, home):
    existing = jobs.list_jobs(include_disabled=True)
    # This integration home is separate from every account's native Cron jobs.
    if len(existing) > 1 or any(j.get('script') != SCRIPT or not j.get('no_agent')
                                or j.get('deliver') != 'local' or j.get('failure_deliver')
                                for j in existing):
        raise MikasaError('审计 Cron home 包含不兼容任务；保留原配置并停止调度')
    job = existing[0] if existing else None
    interval = request['interval']
    if not interval:
        if job and job.get('enabled'):
            job = jobs.pause_job(job['id'], reason=CONFIG_PAUSE)
        if job and job.get('mikasa_interval_seconds') != 0:
            job = jobs.update_job(job['id'], {'mikasa_interval_seconds': 0})
        return job
    if not job:
        job = jobs.create_job('', 'every 1m', name='Mikasa periodic repository audit',
                              script=SCRIPT, no_agent=True, deliver='local',
                              paused=True, paused_reason=CONFIG_PAUSE)
    if job.get('mikasa_interval_seconds') != interval:
        # The SDK accepts a schedule mapping. Fractional minutes retain v1's
        # second precision; do not silently round e.g. 90 seconds to a minute.
        job = jobs.pause_job(job['id'], reason=CONFIG_PAUSE)
        job = jobs.update_job(job['id'], {
            'schedule': {'kind': 'interval', 'minutes': interval / 60, 'display': f'every {interval}s'},
            'mikasa_interval_seconds': interval})
    if job.get('paused_reason') == CONFIG_PAUSE:
        job = jobs.resume_job(job['id'])
    # Unchanged configuration preserves native manual pause/schedule edits.
    return job


def main():
    os.umask(0o077)
    request = json.load(sys.stdin)
    home = Path(os.environ['HERMES_HOME'])
    for path in (home / '.env', home / 'auth.json'):
        if path.exists() or path.is_symlink():
            raise MikasaError('审计 Cron home 不允许认证或 .env 文件')
    for path in (home / 'adapter.lock', home / 'config.yaml', home / 'integration.json',
                 home / 'scripts', home / 'scripts' / SCRIPT, home / 'cron'):
        if path.is_symlink():
            raise MikasaError('审计 Cron 文件不能为外部链接')
    with (home / 'adapter.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Conflict('已有审计 Cron 调度进程运行') from None
        private_write(home / 'config.yaml', json.dumps({
            'plugins': {'enabled': []}, 'cron': {'max_parallel_jobs': 1, 'script_timeout_seconds': 60}}))
        private_write(home / 'scripts' / SCRIPT,
                      (Path(request['root']) / 'workers/hermes/cron_enqueue.py').read_text())
        job = reconcile(request, home)
        private_write(home / 'integration.json', json.dumps({**request, 'job_id': job['id'] if job else None}))
        executed = tick(verbose=False, sync=True, can_dispatch=lambda: not request['paused'] and bool(request['interval']))
        # Re-read after native mark_job_run, including errors and next_run_at.
        current = jobs.get_job(job['id']) if job else None
        if current and current.get('last_status') == 'error' and current.get('last_run_at') != job.get('last_run_at'):
            raise MikasaError('原生定时审计失败；错误已保存在 scheduler/cron 的任务和执行记录中')
        print(json.dumps({'result': {'executed': executed, 'job': current}}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        message = str(exc) if isinstance(exc, MikasaError) else 'Hermes Cron 操作失败（' + type(exc).__name__ + '）'
        print(json.dumps({'error': type(exc).__name__, 'message': message}))
        sys.exit(1)
