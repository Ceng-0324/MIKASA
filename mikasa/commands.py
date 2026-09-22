"""The retained HTTP command surface, isolated from model execution."""
import json
import tempfile

from .errors import MikasaError
from .native import native_installation
from .process import clean_env, run
from .model_settings import validate_model


def resolve(config, text, cancelled=lambda: False):
    source, python = native_installation(config)
    with tempfile.TemporaryDirectory(prefix='mikasa-command-') as home:
        response = run([str(python), str(config.root / 'workers/hermes/command_adapter.py')],
                       cwd=home, timeout=30, limit=100000,
                       env=clean_env({'MIKASA_HERMES_SOURCE': str(source), 'HERMES_HOME': home}),
                       cancelled=cancelled, stdin=json.dumps({'text': text}))
    try:
        envelope = json.loads(response['stdout'])
        result = envelope['result']
        if (response['code'] or envelope['version'] != 1 or not isinstance(result, dict)
                or set(result) != {'name', 'kind', 'target', 'reply'}
                or result['kind'] not in {'switch', 'reset', 'status', 'new', 'help', 'version',
                                          'deferred_command', 'unsupported_command'}
                or not all(result[k] is None or isinstance(result[k], str) for k in ('name', 'target', 'reply'))):
            raise ValueError()
        if result['kind'] == 'switch':
            validate_model(result['target'])
    except (ValueError, TypeError, KeyError, MikasaError):
        raise MikasaError('Hermes 命令组件不可用；检查固定版本，命令未执行') from None
    return result
