#!/usr/bin/env python3
"""Live HTTP chat/CCH acceptance with an ephemeral local API token; no external writes."""
import argparse
import http.client
import json
import os
import secrets
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mikasa.config import Config
from mikasa.model_settings import default_model, validate_model
from mikasa.server import make_server
from mikasa.service import Service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--slash', action='store_true', help='使用 /model 系统命令完成切换与恢复')
    parser.add_argument('--commands', action='store_true', help='同时验证 Hermes 命令与 /new 会话边界')
    args = parser.parse_args()
    config = Config.load(args.config)
    validate_model(args.target)
    if args.target == default_model(config):
        raise SystemExit('请选择与默认模型不同的目标，以验证切换和恢复')
    path = Path(args.report).resolve()
    if not path.is_relative_to(config.runtime):
        raise SystemExit('报告必须位于 runtime 下')
    # Fresh local server; token never written to config, report or stdout.
    token_variable = 'MIKASA_CHAT_PROBE_TOKEN'
    old_token = os.environ.get(token_variable)
    os.environ[token_variable] = secrets.token_urlsafe(40)
    data = json.loads(json.dumps(config.data))
    data['server']['tokens'] = {config.owner: token_variable}
    probe_config = Config(config.root, data)
    server = make_server(Service(probe_config), '127.0.0.1', 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report = {'created': time.time(), 'target': args.target, 'steps': [], 'checks': {}}
    def request(method, route, payload=None, key=None):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=300)
        try:
            conn.request(method, route, None if payload is None else json.dumps(payload),
                         {'Authorization': 'Bearer '+os.environ[token_variable], 'Idempotency-Key': key or uuid.uuid4().hex})
            response = conn.getresponse()
            value = json.loads(response.read())
            if response.status >= 400:
                raise RuntimeError(f'local HTTP {response.status}')
            return value
        finally:
            conn.close()
    try:
        session = request('POST', '/chats', {})
        report['chat_id'] = session['id']
        route = '/chats/'+session['id']
        def send(message, key=None):
            print('Live chat:', message, flush=True)
            result = request('POST', route+'/messages', {'message':message}, key)
            report['steps'].append({'message':message,'response':result})
            with os.fdopen(os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w') as f:
                json.dump(report,f,ensure_ascii=False,indent=2)
            return result
        marker = '蓝鲸-'+secrets.token_hex(3)
        before = send('请记住本次验收代号 '+marker+'，只需简短确认。')
        switch_command = ('/model ' if args.slash else '切换为 ') + args.target
        switched = send(switch_command, 'switch-target')
        replay = request('POST', route+'/messages', {'message':switch_command}, 'switch-target')
        after = send('刚才的验收代号是什么？请原样回答。')
        reset = send('/model default' if args.slash else '恢复默认模型')
        after_reset = send('再复述一次本次验收代号。')
        current = request('GET',route)
        report['checks'] = {
            'switch_effective':switched['model']==args.target and switched['kind']=='switch',
            'target_used_next_turn':after['execution']['requested_model']==args.target,
            'history_survives_switch':marker in after['reply'],
            'retry_idempotent':replay==switched,
            'restored_default':reset['model']==session['model'],
            'history_survives_restore':marker in after_reset['reply'],
            'readback_persisted':current['model']==session['model'] and len(current['turns'])==5,
            'real_hermes':all(r['execution']['backend']=='hermes' for r in [before,switched,after,reset,after_reset]),
        }
        from mikasa.model_settings import model_environment
        target_mode = model_environment(config.data['worker'], args.target).get('MIKASA_MODEL_API_MODE', 'chat_completions')
        default_mode = model_environment(config.data['worker'], session['model']).get('MIKASA_MODEL_API_MODE', 'chat_completions')
        report['checks']['target_protocol'] = all(r['execution'].get('api_mode') == target_mode for r in [switched, after])
        report['checks']['restored_protocol'] = all(r['execution'].get('api_mode') == default_mode for r in [reset, after_reset])
        if args.commands:
            report['checks']['native_history'] = all(r['execution'].get('history_messages', 0) > 0
                                                     and r['execution'].get('session_owner') == 'mikasa'
                                                     for r in [after, after_reset])
            version = send('/v')
            deferred = send('/init')
            new = send('/reset', 'new-session')
            replay_new = request('POST', route+'/messages', {'message': '/reset'}, 'new-session')
            fresh = request('GET', '/chats/'+new['chat_id'])
            report['checks']['official_version'] = version['kind'] == 'version' and 'Hermes' in version['reply']
            report['checks']['init_deferred'] = deferred['kind'] == 'deferred_command' and deferred['execution'] is None
            report['checks']['new_idempotent'] = new == replay_new
            report['checks']['new_session'] = new['chat_id'] != session['id'] and fresh['turns'] == [] and fresh['model'] == current['model']
            report['checks']['old_session_retained'] = len(request('GET', route)['turns']) == 8
            route = '/chats/'+new['chat_id']
            clean = send('如果当前上下文中没有验收代号，请回答“未提供”；否则给出代号。')
            report['checks']['new_history_empty'] = clean['execution'].get('history_messages') == 0 and marker not in clean['reply']
        report['passed']=all(report['checks'].values())
        print(json.dumps({'passed':report['passed'],'checks':report['checks']},ensure_ascii=False),flush=True)
    finally:
        with os.fdopen(os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w') as f:
            json.dump(report,f,ensure_ascii=False,indent=2)
        server.shutdown()
        server.server_close()
        thread.join(3)
        if old_token is None:
            os.environ.pop(token_variable,None)
        else:
            os.environ[token_variable]=old_token
    return 0 if report.get('passed') else 1

if __name__=='__main__':
    raise SystemExit(main())
