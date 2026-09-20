#!/usr/bin/env python3
"""Real CCH acceptance of native memory, skills, identity, isolation and cancellation."""
import argparse
import json
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mikasa.chat import Chat
from mikasa.config import Config
from mikasa.errors import MikasaError
from mikasa.native import HERMES_REVISION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/local/hermes-cch.json')
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    base = Config.load(args.config)
    report_path = Path(args.report).resolve()
    if not report_path.is_relative_to(base.runtime):
        raise SystemExit('report must be inside the configured runtime')
    checks, runtime_evidence = {}, []
    marker = 'memory-' + uuid.uuid4().hex[:12]
    # Short disposable paths also avoid macOS AF_UNIX limits. No production memory mutation.
    with tempfile.TemporaryDirectory(prefix='mkn-', dir='/tmp') as directory:
        data = json.loads(json.dumps(base.data))
        data.update(runtime=directory, members=['native-probe-reader'])
        config = Config(base.root, data)
        with Chat(config) as chat:
            owner = config.owner
            first = chat.create(owner)
            sid = first['id']
            message = ('请实际使用 skill_view 读取 mikasa-review，再使用 memory 工具保存到你的 agent memory：'
                       '这是一条联调测试事实，测试编号是 ' + marker + '。只在完成真实工具调用后简短确认。')
            result = chat.send(sid, owner, message, 'remember')
            runtime_evidence.append(result['execution'])
            gateway = chat.gateways.for_actor(owner)
            home = gateway.home
            events = [json.loads(line) for line in (home/'native-evidence.jsonl').read_text().splitlines()]
            checks['native_skill_view'] = any(e['event']=='tool' and e.get('tool')=='skill_view' and e.get('status')=='ok' for e in events)
            checks['native_memory_write'] = any(e['event']=='tool' and e.get('tool')=='memory' and e.get('status')=='ok' for e in events)
            checks['memory_on_disk'] = marker in (home/'memories/MEMORY.md').read_text()
            checks['normal_replay'] = chat.send(sid, owner, message, 'remember') == result
            saved_key = (home/'.api-key').read_bytes()
            native_rows = gateway.messages(sid)['data']
            checks['native_transcript_has_tools'] = any(r.get('role')=='tool' for r in native_rows)
            with chat.store.connect() as db:
                checks['no_transcript_mirror'] = db.execute('SELECT COUNT(*) FROM chat_turns').fetchone()[0] == 0
                checks['receipt_has_no_prompt'] = marker not in json.dumps([dict(r) for r in db.execute('SELECT * FROM chat_requests')])
        with Chat(config) as chat:
            gateway = chat.gateways.for_actor(owner)
            checks['api_namespace_survives_restart'] = (gateway.home/'.api-key').read_bytes() == saved_key
            checks['native_history_survives_restart'] = gateway.messages(sid)['data'] == native_rows
            checks['replay_survives_restart'] = chat.send(sid, owner, message, 'remember') == result
            new = chat.send(sid, owner, '/new', 'new')
            fresh = chat.get(new['chat_id'], owner)
            checks['new_context_empty'] = fresh['turns'] == []
            recall_text = '从你的长期记忆读取联调测试编号，仅输出编号；如果没有记录则说未提供。'
            recalled = chat.send(new['chat_id'], owner, recall_text, 'recall')
            checks['memory_loaded_after_restart_and_new'] = marker in recalled['reply']
            runtime_evidence.append(recalled['execution'])
            switched = chat.send(new['chat_id'], owner, '/model claude-opus-4-6', 'claude')
            checks['native_cross_protocol_switch'] = switched['kind']=='switch' and switched['model']=='claude-opus-4-6'
            runtime_evidence.append(switched['execution'])
            checks['old_run_evidence_stable'] = chat.send(new['chat_id'], owner, recall_text, 'recall') == recalled
            peer = chat.create('native-probe-reader')
            peer_reply = chat.send(peer['id'], 'native-probe-reader', recall_text, 'peer')
            checks['actor_memory_isolation'] = marker not in peer_reply['reply']
            other = chat.gateways.for_actor('native-probe-reader')
            checks['actor_homes_and_keys_isolated'] = other.home != gateway.home and other.key != gateway.key
            runtime_evidence.append(peer_reply['execution'])
            cancel_session = uuid.uuid4().hex
            gateway.ensure_session(cancel_session, first['model'])
            run = gateway.start(cancel_session, '请详细解释会话恢复。', first['model'], 'cancel-'+uuid.uuid4().hex)
            try:
                gateway.wait(run['run_id'], lambda: True)
            except MikasaError:
                pass
            stop = gateway.request('GET', '/v1/runs/'+run['run_id'])
            deadline = time.monotonic() + 30
            while stop['status'] not in {'cancelled','interrupted','completed','failed'} and time.monotonic() < deadline:
                time.sleep(.2)
                stop = gateway.request('GET', '/v1/runs/'+run['run_id'])
            checks['native_cancel'] = stop['status'] in {'cancelled', 'interrupted'}
            from mikasa.model_settings import model_environment
            credentials = {model_environment(config.data['worker'], m)['MIKASA_MODEL_API_KEY'].encode() for m in (first['model'], 'claude-opus-4-6')}
            checks['no_cch_secrets_written'] = not any(key in p.read_bytes() for p in Path(directory).rglob('*') if p.is_file() and not p.is_symlink() for key in credentials)
        checks['native_injection_all_protocols'] = all(all(e.get(k) for k in ('identity','policy','persona_skill','skills_index')) for e in runtime_evidence)
        checks['protocols_observed'] = {e.get('api_mode') for e in runtime_evidence} == {'codex_responses','anthropic_messages'}
        report = {'created': time.time(), 'hermes_revision': HERMES_REVISION, 'checks': checks,
                  'passed': all(checks.values()), 'protocols': sorted({e.get('api_mode','unknown') for e in runtime_evidence})}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        report_path.chmod(0o600)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
