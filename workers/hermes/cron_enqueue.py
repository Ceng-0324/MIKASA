"""Native no_agent script: one occurrence submits audits to the existing board."""
import json
import os
import sys
from pathlib import Path


def main():
    # Native script subprocess env is sanitized; resolve its own profile without
    # falling back to a personal ~/.hermes or carrying model/platform credentials.
    home = Path(__file__).resolve().parent.parent
    settings = json.loads((home / 'integration.json').read_text())
    os.environ['HERMES_HOME'] = str(home)
    sys.path.insert(0, settings['root'])
    sys.path.insert(0, settings['source'])
    from cron.executions import latest_execution
    from mikasa.config import Config
    from mikasa.kanban import Kanban
    execution = latest_execution(settings['job_id'])
    if not execution or execution['status'] != 'running' or execution['pid'] != os.getppid() or not execution['scheduled_instant']:
        raise RuntimeError('No owned native Cron occurrence')
    config = Config(Path(settings['root']), {
        'runtime': settings['runtime'], 'owner': settings['owner'], 'bot': settings['bot'],
        'members': settings['members'], 'worker': {
            'hermes_source': settings['source'], 'native_python': settings['python']}})
    Kanban(config).call('audit_occurrence', repos=settings['repositories'], actor=settings['owner'],
                       key='cron:' + settings['job_id'] + ':' + execution['scheduled_instant'])
    # Empty stdout is Hermes' native silent-success signal; no external delivery.


if __name__ == '__main__':
    main()
