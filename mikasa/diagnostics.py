"""Explicit model diagnostics through an ephemeral native Hermes CLI."""
import json
import tempfile

from .config import Config
from .errors import MikasaError
from .native import prepare_profile, runtime_environment
from .process import run


def probe_model(config, model):
    with tempfile.TemporaryDirectory(prefix='mikasa-model-probe-') as directory:
        isolated = Config(config.root, {**config.data, 'runtime': directory, 'engineering': {},
                          'github': {'token_env': 'MIKASA_PROBE_NO_GITHUB_TOKEN'}})
        home, source, python, credentials = prepare_profile(isolated, config.owner, engineering=True)
        result = run([str(python), str(config.root / 'workers/hermes/native_engineer.py'),
                      'chat', '--model', model, '--query', '请简短回复：模型连接验证完成。不调用工具。',
                      '--quiet', '--toolsets', 'memory,skills,session_search'],
                     cwd=home / 'workspace', timeout=180,
                     env=runtime_environment(isolated, home, source, python, credentials))
        evidence_path = home / 'native-evidence.jsonl'
        events = [json.loads(line) for line in evidence_path.read_text().splitlines()] if evidence_path.exists() else []
        requests = [e for e in events if e.get('event') == 'request']
        responses = [e for e in events if e.get('event') == 'response']
        if result['code'] or not requests or not responses:
            raise MikasaError('Hermes 原生模型诊断失败；未收到模型响应')
        return {'backend': 'hermes-cli', **requests[-1], **responses[-1]}
