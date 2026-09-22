#!/usr/bin/env python3
"""Real CCH continuity through native CLI sessions, history and shared memory."""
import argparse
import json
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mikasa.config import Config
from mikasa.native import HERMES_REVISION, prepare_profile, runtime_environment
from mikasa.process import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    original = Config.load(args.config)
    with tempfile.TemporaryDirectory(prefix='mkstate-', dir='/tmp') as directory:
        data = {**original.data, 'runtime': directory, 'engineering': {},
                'github': {'token_env': 'MIKASA_PROBE_NO_GITHUB_TOKEN'}}
        config = Config(original.root, data)
        homes = {}
        for engineering in (True, False):
            prepared = prepare_profile(config, config.owner, engineering=engineering)
            home = prepared[0]
            native = json.loads((home / 'config.yaml').read_text())
            native['lsp'] = {'enabled': False}
            (home / 'config.yaml').write_text(json.dumps(native))
            homes[engineering] = prepared

        def invoke(engineering, prompt, resume=None):
            home, source, python, credentials = homes[engineering]
            query = Path(directory) / 'query.txt'
            query.write_text(prompt)
            command = [str(python), str(config.root / 'workers/hermes/native_engineer.py'),
                       'chat', '--model', args.model, '--query-file', str(query), '--quiet',
                       '--toolsets', 'memory,skills,session_search']
            if resume:
                command += ['--resume', resume]
            result = run(command, cwd=home / 'workspace', timeout=240,
                         env=runtime_environment(config, home, source, python, credentials))
            return result['code'] == 0, result['stdout']

        stable = 'stable-' + uuid.uuid4().hex[:12]
        transient = 'task-' + uuid.uuid4().hex[:12]
        ok, _ = invoke(True, f'隔离验收：请通过 memory 工具长期保存这个测试约定：{stable}。'
                       f'当前临时工程名为青桥接续，暂停位置代号为 {transient}，下一步是检查测试结果。'
                       '临时工程内容只留在本次会话，不要写入长期记忆。不要执行其他操作。')
        home = homes[True][0]
        memory = home / 'memories/MEMORY.md'
        text = memory.read_text() if memory.exists() else ''
        checks = {'initial_turn': ok, 'memory_persisted': stable in text,
                  'temporary_task_not_in_memory': transient not in text}
        with sqlite3.connect(home / 'state.db') as db:
            session = db.execute('SELECT id FROM sessions WHERE parent_session_id IS NULL ORDER BY started_at LIMIT 1').fetchone()[0]
        ok, reply = invoke(True, '继续这个会话：给出青桥接续的暂停位置代号和下一步。不要改记忆。', session)
        checks['resume_after_process_restart'] = ok and transient in reply and '测试' in reply
        ok, reply = invoke(True, '这是新会话。继续上次青桥接续的工程，找回临时暂停位置代号、下一步和长期测试约定。不要修改记忆。')
        checks['new_session_recovers_history'] = ok and transient in reply and stable in reply
        ok, reply = invoke(False, '长期记忆中的 stable- 开头的测试约定是什么？直接回答，不修改记忆。')
        checks['chat_reads_shared_engineering_memory'] = ok and stable in reply
        events = [json.loads(line) for line in (home / 'native-evidence.jsonl').read_text().splitlines()]
        checks['native_history_tool_used'] = any(e.get('tool') == 'session_search' for e in events)
        requests = [e for e in events if e.get('event') == 'request']
        checks['identity_and_skills_loaded'] = bool(requests) and all(
            all(e.get(k) for k in ('identity', 'policy', 'persona_skill', 'skills_index')) for e in requests)
        checks['temporary_task_still_not_in_memory'] = transient not in memory.read_text()
        print(json.dumps({'hermes_revision': HERMES_REVISION, 'model': args.model,
                          'checks': checks, 'passed': all(checks.values()),
                          'scope': 'isolated native CLI; no external messages or production memory writes'},
                         ensure_ascii=False, indent=2))
        return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
