import argparse
import json
import os
import shutil
import sys

from .config import Config
from .errors import MikasaError
from .diagnostics import probe_model as run_model_probe


def parser():
    p = argparse.ArgumentParser(description='Mikasa：身份与集成；Hermes 原生执行')
    p.add_argument('--config', default='config/examples/mikasa.json')
    commands = p.add_subparsers(dest='command', required=True)
    diagnostic = commands.add_parser('doctor')
    diagnostic.add_argument('--probe-model', action='store_true', help='临时原生 CLI 模型探针，会消耗额度')
    diagnostic.add_argument('--model', help='只诊断指定模型，不改变默认值')
    engineer = commands.add_parser('engineer', help='-- 后参数直接交给完整 Hermes CLI')
    engineer.add_argument('--cwd', help='实际仓库或工作目录')
    engineer.add_argument('arguments', nargs=argparse.REMAINDER)
    connections = commands.add_parser('connections', help='平台检查；--probe 只读联网')
    connections.add_argument('platform', choices=('github', 'feishu', 'weixin'))
    connections.add_argument('--probe', action='store_true')
    gateway = commands.add_parser('gateway', help='统一 Hermes 消息 Gateway')
    gateway.add_argument('--platform', choices=('feishu', 'weixin'), action='append', required=True)
    commands.add_parser('weixin-login')
    chat = commands.add_parser('chat', help='原生 Hermes 聊天 CLI')
    chat.add_argument('--session')
    backup = commands.add_parser('backup', help='停服后备份受管状态到新目录')
    backup.add_argument('destination')
    restore = commands.add_parser('restore', help='校验备份并恢复到新 runtime')
    restore.add_argument('source')
    restore.add_argument('destination')
    return p


def doctor(config, *, probe_model=False, selected_model=None):
    from .skills import skill_inventory
    from .model_settings import model_diagnostics
    from .native import native_installation
    settings = config.data.get('worker', {})
    model = model_diagnostics(settings, selected_model)
    if probe_model and model['configuration'] == 'valid':
        try:
            runtime = run_model_probe(config, model['requested_model'])
        except MikasaError as exc:
            model.update(connection='failed', error=str(exc))
        else:
            reported = runtime.get('reported_model')
            model.update(connection='passed', backend=runtime.get('backend'), reported_model=reported,
                         model_match='unreported' if not reported else 'same' if reported == model['requested_model'] else 'different',
                         identity_note='响应标识不能独立证明底层模型身份')
    try:
        native_installation(config)
        native = {'installation': 'ready', 'execution': 'not_checked'}
    except (MikasaError, OSError, ValueError):
        native = {'installation': 'unavailable', 'execution': 'not_checked'}
    deprecated = ['worker.' + k for k in ('command', 'home', 'timeout', 'max_attempts', 'max_output_bytes', 'max_context_bytes') if k in settings]
    deprecated += [name for name, enabled in (
        ('schedules', bool(config.data.get('schedules'))),
        ('server', 'server' in config.data),
        ('github.publish_enabled', 'publish_enabled' in config.data.get('github', {}))) if enabled]
    return {'python': sys.version.split()[0], 'git': bool(shutil.which('git')), 'gh': bool(shutil.which('gh')),
            'rules': 'loaded', 'skills': skill_inventory(config.root), 'native': native, 'model': model,
            'github_token_present': bool(os.environ.get(config.data.get('github', {}).get('token_env', 'MIKASA_GITHUB_TOKEN'))),
            'deprecated_settings': deprecated,
            'note': '旧 worker/runner 配置不再执行。聊天与工程 CLI 的工具、预算、调度均由 Hermes 原生配置管理；外部能力需独立验证。'}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        config = Config.load(args.config)
        if args.command == 'engineer':
            from .engineering_cli import launch
            return launch(config, args.arguments, cwd=args.cwd)
        if args.command == 'weixin-login':
            from .connections import login_weixin
            return login_weixin(config)
        if args.command == 'connections':
            from .connections import diagnostics
            value = diagnostics(config, args.platform, probe=args.probe)
            print(json.dumps(value, ensure_ascii=False, indent=2))
            return int(value['configuration'] != 'ready' or (args.probe and value['connection'] != 'passed'))
        if args.command == 'gateway':
            from .native import interactive
            return interactive(config, platforms=args.platform)
        if args.command == 'doctor':
            value = doctor(config, probe_model=args.probe_model, selected_model=args.model)
            print(json.dumps(value, ensure_ascii=False, indent=2))
            return int(args.probe_model and value['model']['connection'] != 'passed')
        if args.command == 'chat':
            from .native import interactive
            return interactive(config, args.session)
        elif args.command == 'backup':
            from .backup import backup_state
            value = backup_state(config, args.destination)
        elif args.command == 'restore':
            from .backup import restore_state
            value = restore_state(config, args.source, args.destination)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    except MikasaError as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
