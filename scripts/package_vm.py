#!/usr/bin/env python3
"""Package a clean committed checkout, never local configuration or runtime data."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile


def package(root, destination):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args])
    if git('status', '--porcelain', '--untracked-files=normal').strip():
        raise RuntimeError('先提交已验证的改动；发布包只接受干净 checkout')
    revision = git('rev-parse', 'HEAD').decode().strip()
    if destination.exists():
        raise RuntimeError('发布包已存在，拒绝覆盖')
    files = {}
    archive = git('archive', '--format=tar', revision)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source, tarfile.open(destination, 'w:gz') as target:
        for item in source.getmembers():
            if item.isdir():
                target.addfile(item)
            elif item.isfile():
                content = source.extractfile(item).read()
                files[item.name] = hashlib.sha256(content).hexdigest()
                target.addfile(item, io.BytesIO(content))
            else:
                raise RuntimeError('发布源码不允许符号链接或特殊文件')
        data = json.dumps({'revision': revision, 'files': files}, sort_keys=True).encode()
        item = tarfile.TarInfo('release.json')
        item.size, item.mode = len(data), 0o644
        target.addfile(item, io.BytesIO(data))
    print(json.dumps({'revision': revision, 'archive': str(destination)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    package(Path(__file__).resolve().parents[1], args.destination.resolve())
