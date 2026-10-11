"""Build reproducible release artifacts and a SHA-256 manifest."""
import gzip
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / 'dist'
    destination.mkdir(exist_ok=True)
    subprocess.run([os.sys.executable, str(ROOT / 'runtime/comments/package.py')], check=True)
    environment = {**os.environ, 'SOURCE_DATE_EPOCH': '315532800'}
    with tempfile.TemporaryDirectory() as temporary:
        component = Path(temporary) / 'moderation'
        shutil.copytree(ROOT / 'components/moderation', component,
                        ignore=shutil.ignore_patterns('build', '*.egg-info', '__pycache__'))
        for path in component.rglob('*'):
            if path.is_file(): path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n'))
        subprocess.run([os.sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation',
                        str(component), '-w', str(destination)], check=True, env=environment)
    for wheel in destination.glob('web_platform_moderation-*.whl'):
        with zipfile.ZipFile(wheel) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        with zipfile.ZipFile(wheel, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(members.items()):
                item = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                item.create_system = 3
                item.external_attr = 0o100644 << 16
                item.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(item, data)
    for filename, source, entry in [('invalidation.zip', ROOT / 'modules/static-site/lambda/lambda_function.py', 'lambda_function.py'),
                                     ('alert-mail.zip', ROOT / 'modules/journal-comments/alerts/handler.py', 'handler.py')]:
        with zipfile.ZipFile(destination / filename, 'w', zipfile.ZIP_DEFLATED) as archive:
            item = zipfile.ZipInfo(entry, (1980, 1, 1, 0, 0, 0))
            item.create_system = 3
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o644 << 16
            archive.writestr(item, source.read_bytes())
    files = sorted(p for p in destination.iterdir() if p.suffix in {'.gz', '.zip', '.whl'})
    (destination / 'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in files), newline='\n')
    print('Built release artifacts with checksums.')


if __name__ == '__main__': main()
