"""Pinned Hermes database copier; no model, providers or credentials loaded."""
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.environ['MIKASA_HERMES_SOURCE'])
from hermes_cli.backup import copy_db_and_verify
import yaml

SECRETS = {'api_key', 'token', 'access_token', 'refresh_token', 'secret', 'client_secret', 'password', 'authorization'}


def relocate(value, paths):
    if not isinstance(value, str):
        return value
    for old, new in paths:
        if value == old or value.startswith(old + '/'):
            return new + value[len(old):]
    return value


def configuration(value, paths):
    if isinstance(value, dict):
        return {k: configuration(v, paths) for k, v in value.items() if str(k).lower() not in SECRETS}
    if isinstance(value, list):
        return [configuration(v, paths) for v in value]
    return relocate(value, paths)


def main():
    os.umask(0o077)
    request = json.load(sys.stdin)
    move = request.get('relocation')
    paths = [(move['old_runtime'], move['runtime']), (move['old_root'], move['root'])] if move else []
    for item in request['files']:
        src, dst = Path(item['source']), Path(item['target'])
        with src.open('rb') as stream:
            database = stream.read(16) == b'SQLite format 3\x00'
        if database:
            if not copy_db_and_verify(src, dst):
                raise ValueError('SQLite snapshot failed')
        elif item.get('config'):
            value = yaml.safe_load(src.read_text())
            if not isinstance(value, dict):
                raise ValueError('Invalid profile configuration')
            dst.write_text(json.dumps(configuration(value, paths), ensure_ascii=False, indent=2))
        else:
            shutil.copyfile(src, dst)
    if move:
        # Only live operational pointers move; transcripts/events retain historical paths.
        with sqlite3.connect(Path(move['stage']) / 'kanban/kanban.db') as db:
            for task, workspace, raw in db.execute('SELECT id, workspace_path, result FROM tasks').fetchall():
                result = json.loads(raw) if raw else None
                if isinstance(result, dict) and isinstance(result.get('result'), dict):
                    value = result['result']
                    if 'workspace' in value:
                        value['workspace'] = relocate(value['workspace'], paths[:1])
                db.execute('UPDATE tasks SET workspace_path=?, result=? WHERE id=?',
                           (relocate(workspace, paths[:1]), json.dumps(result) if raw else raw, task))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Native state snapshot/restore failed') from None
