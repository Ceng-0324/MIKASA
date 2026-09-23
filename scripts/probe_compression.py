#!/usr/bin/env python3
"""Real CCH automatic compression in a temporary Hermes profile; no production messages or state writes."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def native_probe():
    sys.path.insert(0, os.environ['MIKASA_HERMES_SOURCE'])
    from hermes_cli.config import load_config
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from agent.conversation_compression import is_compaction_progress_status
    from run_agent import AIAgent
    config = load_config()
    model = config['model']['default']
    provider = config['model']['provider']
    runtime = resolve_runtime_provider(requested=provider, target_model=model)
    statuses = []
    agent = AIAgent(model=model, **{k: runtime[k] for k in ('provider', 'api_mode', 'base_url', 'api_key')},
                    requested_provider=provider, enabled_toolsets=[], quiet_mode=True,
                    skip_context_files=True, skip_memory=True, skip_background_review=True,
                    max_iterations=3, reasoning_config={'effort': 'low'},
                    status_callback=lambda *a, **kw: statuses.append(a))
    marker = 'compression-probe-bluebridge-0923'
    history = []
    for i in range(60):
        history.append({'role': 'user', 'content': f'Inspect synthetic module {i}. ' +
                        'Preserve public signatures and validate the change. ' * 20})
        history.append({'role': 'assistant', 'content': f'Module {i} inspection complete. ' +
                        'The synthetic unit checks passed; no deployment or external writes occurred. ' * 30})
    history[50]['content'] += f' The release acceptance marker is {marker}. Preserve this exact marker for handoff.'
    started = time.monotonic()
    try:
        compressor = agent.context_compressor
        # Native preflight deliberately waits for provider-reported usage on a fresh history.
        # Obtain that real measurement, then let the next turn trigger compression itself.
        measured = agent.run_conversation('Acknowledge this synthetic handoff. Reply READY only.',
                                          conversation_history=history)
        prompt_tokens = compressor.last_real_prompt_tokens
        result = agent.run_conversation('What is the release acceptance marker? Reply with the exact marker only.',
                                        conversation_history=measured['messages'])
        telemetry = compressor._last_compression_telemetry or {}
        checks = {
            'automatic_trigger': telemetry.get('trigger_source') == 'auto',
            'compression_committed': compressor.compression_count > 0,
            'history_reduced': len(result.get('messages', [])) < len(history),
            'middle_fact_retained': marker in (result.get('final_response') or ''),
            'progress_emitted': any(a and is_compaction_progress_status(str(a[-1])) for a in statuses),
        }
        print('MIKASA_COMPRESSION=' + json.dumps({'checks': checks, 'passed': all(checks.values()),
            'telemetry': {k: telemetry.get(k) for k in ('trigger_source', 'aux_model', 'aux_provider',
                'aux_prompt_tokens', 'failure_class')},
            'compression_count': compressor.compression_count, 'measured_prompt_tokens': prompt_tokens,
            'threshold_tokens': compressor.threshold_tokens, 'elapsed_seconds': round(time.monotonic() - started, 1)}))
        return int(not all(checks.values()))
    finally:
        agent.close()


def main():
    from mikasa.config import Config
    from mikasa.native import HERMES_REVISION, prepare_profile, runtime_environment
    from mikasa.process import run
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--summary-model', required=True)
    parser.add_argument('--fallback-model', required=True)
    parser.add_argument('--force-fallback', action='store_true', help='Simulate primary connection failure; backup still calls real CCH')
    args = parser.parse_args()
    original = Config.load(args.config)
    with tempfile.TemporaryDirectory(prefix='mkcompress-', dir='/tmp') as directory:
        data = {**original.data, 'runtime': directory, 'engineering': {},
                'github': {'token_env': 'MIKASA_PROBE_NO_GITHUB_TOKEN'}}
        config = Config(original.root, data)
        home, source, python, credentials = prepare_profile(config, config.owner)
        path = home / 'config.yaml'
        native = json.loads(path.read_text())
        routes = [native['model_aliases'][m] for m in (args.summary_model, args.fallback_model)]
        native['compression'] = {'enabled': True, 'progress_notices': True, 'threshold_tokens': 32000}
        native['auxiliary'] = {'compression': {**routes[0], 'reasoning_effort': 'low',
            'timeout': 300, 'no_progress_timeout': 120, 'fallback_chain': [routes[1]]}}
        native['agent'].update(max_turns=3, auto_recovery_cycles=0)
        native['plugins'] = {'enabled': []}
        native['skills'] = {'auto_load': []}
        native['lsp'] = {'enabled': False}
        # Reserve an unlistening loopback port: a real connection refusal without contacting a third party.
        with socket.socket() as unavailable:
            unavailable.bind(('127.0.0.1', 0))
            if args.force_fallback:
                native['providers']['probe-unavailable'] = {
                    'base_url': f'http://127.0.0.1:{unavailable.getsockname()[1]}/v1',
                    'api_key': 'synthetic-unavailable', 'api_mode': 'chat_completions'}
                native['auxiliary']['compression']['provider'] = 'probe-unavailable'
            path.write_text(json.dumps(native))
            env = runtime_environment(config, home, source, python, credentials)
            env['HERMES_ENABLE_PROJECT_PLUGINS'] = '0'
            reply = run([str(python), str(Path(__file__).resolve()), '--native'],
                        cwd=home / 'workspace', env=env, timeout=720)
        report = next((json.loads(line.split('=', 1)[1]) for line in reply['stdout'].splitlines()
                       if line.startswith('MIKASA_COMPRESSION=')), None)
        if report is None:
            raise RuntimeError('Native compression probe failed before producing safe telemetry; raw output suppressed')
        report.update(hermes_revision=HERMES_REVISION, forced_primary_failure=args.force_fallback)
        expected = args.fallback_model if args.force_fallback else args.summary_model
        report['checks']['configured_summary_route_used'] = report['telemetry']['aux_model'] == expected
        report['passed'] = reply['code'] == 0 and all(report['checks'].values())
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(not report['passed'])


if __name__ == '__main__':
    try:
        raise SystemExit(native_probe() if sys.argv[1:] == ['--native'] else main())
    except Exception as exc:
        # Provider errors can contain URLs or authentication details. Keep output content-free.
        raise SystemExit(f'Compression probe failed ({type(exc).__name__}); credentials and raw responses withheld') from None
