#!/usr/bin/env python3
"""Actual native Docker read-only and forced-cancellation checks; no model requests."""
import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mikasa.config import Config
from mikasa.errors import MikasaError
from mikasa.native import HERMES_REVISION, private_write, verify_source
from mikasa.native_tools import NativeToolSession
from mikasa.process import clean_env, git, run
from mikasa.workspace import Workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/local/hermes-cch.json')
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    base = Config.load(args.config)
    report = Path(args.report).resolve()
    if not report.is_relative_to(base.runtime):
        raise MikasaError('报告必须位于 runtime')
    source = (base.root / base.data['worker']['hermes_source']).resolve()
    verify_source(source)
    python = base.data['worker']['command'][0]
    checks = {}
    with tempfile.TemporaryDirectory(prefix='mke-', dir='/tmp') as directory:
        root = Path(directory)
        repository = root / 'repo'
        repository.mkdir()
        (repository / 'calc.py').write_text('VALUE = 1\n')
        git(['init', '-b', 'main'], repository)
        git(['add', '.'], repository)
        git(['-c', 'user.name=Probe', '-c', 'user.email=probe@example.invalid', 'commit', '-m', 'fixture'], repository)
        data = json.loads(json.dumps(base.data))
        data['runtime'] = str(root / 'state')
        data['repositories'] = {'local/probe': {'source': str(repository), 'base': 'main', 'checks': []}}
        config = Config(base.root, data)
        task = {'id': 'offline', 'payload': {'kind': 'review', 'repo': 'local/probe'}}
        workspace = Workspace(config, task, 'proof').prepare()
        home = root / 'home'
        home.mkdir()
        env = clean_env({'PYTHONPATH': str(source), 'HERMES_HOME': str(home),
                         'MIKASA_MODEL_API_KEY': 'synthetic-secret-must-not-cross'})
        with NativeToolSession(workspace, 'review', lambda: False) as session:
            private_write(home / 'config.yaml', json.dumps({'terminal': session.snapshot.terminal_config(),
                                                           'plugins': {'enabled': []}}))
            env['MIKASA_PROBE_TASK'] = session.native_id
            code = '''import json,os
from tools.file_tools import read_file_tool,write_file_tool
from tools.terminal_tool import terminal_tool,cleanup_all_environments
from tools.environments.docker import DockerEnvironment
task=os.environ['MIKASA_PROBE_TASK']
try:
 read=read_file_tool('/workspace/calc.py',task_id=task)
 write=json.loads(write_file_tool('/workspace/calc.py','VALUE = 9\\n',task_id=task))
 shell=json.loads(terminal_tool("echo overwrite > /workspace/calc.py",task_id=task,timeout=10))
 print(json.dumps({'read':read,'write_blocked':bool(write.get('error')) or write.get('success') is False,
                   'shell_write_blocked':shell.get('exit_code')!=0}))
finally:
 cleanup_all_environments()
 DockerEnvironment.wait_for_all_teardowns(timeout=15)
'''
            result = run([python, '-c', code], cwd=home, env=env, timeout=90)
            if result['code']:
                raise MikasaError('原生只读探针执行失败')
            observed = json.loads(result['stdout'].strip().splitlines()[-1])
            checks['native_readonly_file_write_blocked'] = observed['write_blocked']
            checks['native_readonly_shell_write_blocked'] = observed['shell_write_blocked']
            checks['real_read_output_validates_head'] = session.snapshot.observe_read('calc.py', observed['read']).get('complete') is True
            checks['readonly_source_unchanged'] = (workspace.path / 'calc.py').read_text() == 'VALUE = 1\n'
            session.finish()
        with NativeToolSession(workspace, 'implement', lambda: False) as session:
            private_write(home / 'config.yaml', json.dumps({'terminal': session.snapshot.terminal_config(),
                                                           'plugins': {'enabled': []}}))
            env['MIKASA_PROBE_TASK'] = session.native_id
            last_poll, seen = 0, False

            def cancel_after_start():
                nonlocal last_poll, seen
                now = time.monotonic()
                if now - last_poll > .5:
                    last_poll = now
                    seen = bool(session.containers())
                return seen

            code = "from tools.terminal_tool import terminal_tool; import os; terminal_tool('sleep 120',task_id=os.environ['MIKASA_PROBE_TASK'],timeout=150)"
            started = time.monotonic()
            try:
                run([python, '-c', code], cwd=home, env=env, timeout=60, cancelled=cancel_after_start)
                checks['forced_cancel_observed'] = False
            except MikasaError as exc:
                checks['forced_cancel_observed'] = seen and '取消' in str(exc)
            checks['cancel_is_bounded'] = time.monotonic() - started < 60
        checks['cancelled_container_removed'] = not session.containers()
        checks['cancelled_snapshot_removed'] = not session.snapshot.path.exists()
    evidence = {'hermes_revision': HERMES_REVISION, 'checks': checks, 'passed': all(checks.values())}
    private_write(report, json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence, indent=2))
    return 0 if evidence['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
