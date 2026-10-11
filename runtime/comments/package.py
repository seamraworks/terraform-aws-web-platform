#!/usr/bin/env python3
"""Build a reproducible, secret-free runtime with the standalone moderation package."""
import argparse
import gzip
import io
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parent
PLATFORM = ROOT.parent.parent
FILES = ['Dockerfile', '.dockerignore', 'requirements.txt', 'moderator.py', 'operations.py', 'digest.py',
         'deployment.py', 'render-runtime.py', 'host-config.py', 'refresh-proxies.py', 'install.sh',
         'storage-guard.py', 'storage-cleanup.sh', 'README.md']


def build(destination):
    files = [(ROOT / name, name) for name in FILES]
    files += [(p, str(p.relative_to(ROOT)).replace('\\', '/')) for p in (ROOT / 'templates').rglob('*.tmpl')]
    component = PLATFORM / 'components/moderation/src'
    files += [(p, 'moderation/' + str(p.relative_to(component)).replace('\\', '/')) for p in component.rglob('*.py')]
    files += [(PLATFORM / 'LICENSE', 'LICENSE'), (PLATFORM / 'NOTICE', 'NOTICE')]
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('wb') as output, gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w', format=tarfile.PAX_FORMAT) as archive:
            for path, name in sorted(files, key=lambda pair: pair[1]):
                data = path.read_bytes().replace(b'\r\n', b'\n')
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                entry.mode = 0o755 if name.endswith('.sh') else 0o644
                archive.addfile(entry, io.BytesIO(data))
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(PLATFORM / 'dist/web-comments.tar.gz'))
    print(build(parser.parse_args().output))
