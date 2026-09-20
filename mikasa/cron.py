"""Wake the pinned Hermes Cron scheduler; Hermes owns schedules and occurrences."""
import json

from .errors import Conflict, MikasaError
from .native import verify_source
from .process import clean_env, run


class Cron:
    def __init__(self, config, tasks):
        self.config, self.tasks = config, tasks
        self.home = config.runtime / 'scheduler'

    def tick(self, paused=False):
        interval = self.config.data.get('schedules', {}).get('audit_interval_seconds', 0)
        if not interval and not self.home.exists():
            return {'executed': 0, 'job': None}
        verify_source(self.tasks.source)
        if self.home.is_symlink():
            raise MikasaError('Cron home 不能为外部链接')
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        request = {'interval': interval, 'paused': paused, 'root': str(self.config.root),
                   'runtime': str(self.config.runtime), 'owner': self.config.owner, 'bot': self.config.bot,
                   'members': self.config.data.get('members', []),
                   'repositories': list(self.config.data['repositories']),
                   'source': str(self.tasks.source), 'python': str(self.tasks.python.absolute())}
        result = run([str(self.tasks.python.absolute()), str(self.config.root / 'workers/hermes/cron_adapter.py')],
                     cwd=self.home, stdin=json.dumps(request), timeout=90,
                     env=clean_env({'HERMES_HOME': str(self.home),
                                    'MIKASA_HERMES_SOURCE': str(self.tasks.source),
                                    'HERMES_ENABLE_PROJECT_PLUGINS': '0'}))
        try:
            reply = json.loads(result['stdout'])
        except ValueError:
            raise MikasaError('Hermes Cron 响应无效；检查原生执行记录') from None
        if result['code'] or 'error' in reply:
            kind = Conflict if reply.get('error') == 'Conflict' else MikasaError
            raise kind(reply.get('message', 'Hermes Cron 执行失败；检查原生执行记录'))
        return reply['result']
