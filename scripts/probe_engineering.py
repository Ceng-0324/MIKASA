#!/usr/bin/env python3
"""Real CCH engineering through the public native CLI; disposable repo and account state."""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from contextlib import ExitStack
from types import SimpleNamespace
from urllib.request import Request, urlopen
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mikasa.config import Config
from mikasa.native import HERMES_REVISION, NativeGateway, prepare_profile, profile_home
from mikasa.process import git
from mikasa.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--report', help='Optional private summary; omitted by default')
    parser.add_argument('--entry', choices=('cli', 'gateway'), default='cli')
    args = parser.parse_args()
    original = Config.load(args.config)
    checks = {}
    with ExitStack() as stack:
        directory = stack.enter_context(tempfile.TemporaryDirectory(prefix='mkeng-', dir='/tmp'))
        root = Path(directory).resolve()
        data = {**original.data, 'project_root': str(original.root), 'runtime': str(root/'state'),
                'engineering': {}, 'github': {'token_env': 'MIKASA_PROBE_NO_GITHUB_TOKEN'}}
        config = Config(original.root, data)
        path = root/'config.json'
        path.write_text(json.dumps(data))
        repo = root/'repo'
        repo.mkdir()
        git(['init', '-b', 'main'], repo)
        git(['config', 'user.name', 'Mikasa Probe'], repo)
        git(['config', 'user.email', 'probe@example.invalid'], repo)
        (repo/'calc.py').write_text('def add(a, b):\n    return a - b\n')
        (repo/'test_calc.py').write_text('import unittest\nfrom calc import add\nclass TestAdd(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n        self.assertEqual(add(-2, 3), 1)\n')
        (repo/'AGENTS.md').write_text('Synthetic test repo. Only edit this repository. Do not contact external services or publish.\n')
        git(['add', '.'], repo)
        git(['commit', '-m', 'fixture baseline'], repo)
        baseline = git(['rev-parse', 'HEAD'], repo)
        home, *_ = prepare_profile(config, config.owner, engineering=args.entry == 'cli')
        # Optional language servers are unrelated to this probe and need no downloads.
        native = json.loads((home/'config.yaml').read_text())
        native['lsp'] = {'enabled': False}
        native['approvals'] = {'mode': 'off'}
        native['terminal']['cwd'] = str(repo)
        (home/'config.yaml').write_text(json.dumps(native))
        marker = '工程续话' + uuid.uuid4().hex[:12]
        prompt = root/'query.txt'
        prompt.write_text(f'''这是隔离的原生工程验收，请在合成仓库 {repo} 完成并验证：
1. 读取 AGENTS.md 与 calc.py，读取 mikasa-implement skill；运行 unittest 观察失败，修复 add 并复验。
2. 用原生工具创建 .github/workflows/fixture.yml（内容为 name: fixture）。使用 terminal 写入 asset.bin，内容必须为 bytes(range(256))。不要改 AGENTS.md；原生规则文件审批另行验证。
3. 通过 terminal background=true 启动一个等待 30 秒的 Python 程序；使用 process_manage 查看其状态并终止，不留下后台进程。
4. 用 delegate_task 委派一次只读检查：检查 calc.py 的修复与测试是否一致，不能修改文件或访问外部服务。
5. 用原生 memory 将“{marker}”存到长期记忆。验证文件和测试后创建一个本地 Git 提交。
不推送、不发布、不访问外部账号、不修改仓库外文件（原生记忆除外）。最后自然语言说明实际结果，不输出 JSON。''')

        gateway, chat_id, events = None, uuid.uuid4().hex, []
        if args.entry == 'gateway':
            Store(config.runtime)
            gateway = stack.enter_context(NativeGateway(config, config.owner))
            gateway.create(chat_id, args.model)

        def invoke(arguments):
            if gateway:
                run = gateway.start(chat_id, prompt.read_text(), args.model, uuid.uuid4().hex)
                request = Request(gateway.url + '/v1/runs/' + run['run_id'] + '/events', headers={
                    'Authorization': 'Bearer ' + gateway.key, 'Accept': 'text/event-stream'})
                # Single SSE consumer; observe names only, never persist content or tool arguments.
                with urlopen(request, timeout=60) as response:
                    for line in response:
                        if line.startswith(b'data:'):
                            event = json.loads(line[5:])
                            events.append(event.get('event'))
                            if event.get('event') in ('run.completed','run.failed','run.cancelled','run.interrupted'):
                                break
                result = gateway.wait(run['run_id'])
                return SimpleNamespace(returncode=0 if result['status'] == 'completed' else 1,
                                       stdout=result.get('output',''))
            command = [sys.executable, '-B', '-m', 'mikasa', '--config', str(path), 'engineer', '--cwd', str(repo), '--', *arguments]
            return subprocess.run(command, cwd=original.root, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=900)

        result = invoke(['chat', '--model', args.model, '--query-file', str(prompt), '--quiet', '--yolo'])
        checks['native_entry_completed'] = result.returncode == 0
        tested = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-v'], cwd=repo, capture_output=True)
        checks['actual_tests_pass'] = tested.returncode == 0
        checks['git_commit_created'] = git(['rev-parse', 'HEAD'], repo) != baseline
        checks['binary_exact'] = (repo/'asset.bin').is_file() and (repo/'asset.bin').read_bytes() == bytes(range(256))
        checks['workflow_written'] = (repo/'.github/workflows/fixture.yml').is_file()
        checks['rules_preserved'] = (repo/'AGENTS.md').read_text().startswith('Synthetic test repo.')
        memory = profile_home(config, config.owner)/'memories/MEMORY.md'
        checks['shared_memory_written'] = memory.exists() and marker in memory.read_text()
        session = None
        if (home/'state.db').exists():
            with sqlite3.connect(home/'state.db') as db:
                row = db.execute("SELECT id FROM sessions WHERE parent_session_id IS NULL ORDER BY started_at LIMIT 1").fetchone()
                session = row[0] if row else None
        checks['native_session_saved'] = bool(session)
        if session:
            prompt.write_text('继续刚才的会话：用 terminal 再运行一次 unittest，读取长期记忆中的工程续话标记并在自然语言回复中给出。不要再改文件或提交。')
            resumed = invoke(['chat', '--resume', session, '--model', args.model, '--query-file', str(prompt), '--quiet', '--yolo'])
            checks['native_resume_and_memory'] = resumed.returncode == 0 and marker in resumed.stdout
            if not checks['native_resume_and_memory']:
                print(json.dumps({'synthetic_resume_reply': resumed.stdout[:3000], 'expected_marker': marker}, ensure_ascii=False))
        evidence = [json.loads(line) for line in (home/'native-evidence.jsonl').read_text().splitlines()] if (home/'native-evidence.jsonl').exists() else []
        tools = sorted({e.get('tool') for e in evidence if e.get('event') == 'tool'})
        requests = [e for e in evidence if e.get('event') == 'request']
        primary_requests = [e for e in requests if e.get('session_id') == session]
        checks['identity_skills_loaded'] = bool(primary_requests) and all(all(e.get(k) for k in ('identity','policy','persona_skill','skills_index')) for e in primary_requests)
        for tool in ('terminal','process_manage','delegate_task','memory','skill_view'):
            checks['native_' + tool] = tool in tools
        # Dispatcher and scheduler use the public native commands, no Mikasa runner.
        if gateway:
            checks['native_progress_events'] = 'tool.started' in events and 'tool.completed' in events
            checks['native_final_event'] = 'run.completed' in events
        else:
            for command in ('kanban', 'cron'):
                checks[command + '_entry'] = invoke([command, '--help']).returncode == 0
        report = {'hermes_revision': HERMES_REVISION, 'requested_model': args.model,
                  'checks': checks, 'tools_observed': tools,
                  'reported_models': sorted({e['reported_model'] for e in evidence if e.get('reported_model')}),
                  'passed': all(checks.values()),
                  'entry': args.entry, 'events': sorted(set(events)),
                  'scope': 'disposable repo and profile; Gateway uses local API, no messaging-platform delivery'}
        if args.report:
            output = Path(args.report)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
            output.chmod(0o600)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report['passed']:
            print(json.dumps({'synthetic_task_reply': result.stdout[:4000]}, ensure_ascii=False))
        return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
