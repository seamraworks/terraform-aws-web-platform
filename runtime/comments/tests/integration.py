"""Disposable real Remark42/Caddy checks. No AWS or OpenAI calls.

Run from comments/: python tests/integration.py
Only uniquely named containers created by this script are stopped and removed.
"""
import copy
import io
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from moderator import Database, Remark, Worker, decode_export
from operations import Storage, compare_exports, encode_export, restore, recover, import_snapshot
from test_moderator import comment, Model

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runtime_package', ROOT / 'package.py')
runtime_package = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime_package)
spec = importlib.util.spec_from_file_location('runtime_renderer', ROOT / 'render-runtime.py')
runtime_renderer = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime_renderer)
from deployment import load_deployment
REMARK = 'umputun/remark42:v1.17.1@sha256:8da1a3b77846f4b1ab9cb20b1faf5069f7f03c5081c3269fee2801f53e77bde1'
CADDY = 'caddy:2@sha256:13b7fbadd017b042956fddbceedeeea12bb1e560534f9b3df281269dbcc61813'


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.STDOUT).strip()


class LocalS3:
    """Real archive code, in-memory object storage; no real account credentials."""
    def __init__(self): self.objects = {}
    def upload_file(self, source, bucket, key, **_): self.objects[key] = Path(source).read_bytes()
    def get_object(self, Bucket, Key):
        data = self.objects[Key]
        class Body(io.BytesIO):
            def iter_chunks(self, size):
                while chunk := self.read(size): yield chunk
        return {'ContentLength': len(data), 'Body': Body(data)}


def run(base, directory):
    config = {'site': 'example', 'admin_password': 'integration-admin', 'mode': 'auto',
              'remark_url': base, 'ops_dir': str(directory / 'ops'),
              'article_hosts': ['www.example.com'], 'article_path_prefix': '/journal/'}
    remark = Remark(config)
    for _ in range(40):
        try: metadata = decode_export(remark.export())[0]; break
        except Exception: time.sleep(.5)
    else: raise RuntimeError('Remark42 did not become ready')
    records = [metadata, comment(), comment('c2', pid='c1'),
               comment('c3', locator={'site': 'example', 'url': 'https://www.example.com/journal/other.html'})]
    remark.request('POST', 'admin/import', body=encode_export(records), provider='remark')
    remark.request('GET', 'admin/wait', timeout='20s')
    remark.request('PUT', 'admin/user/google_blocked', block='1')
    remark.request('PUT', 'admin/readonly', url=records[-1]['locator']['url'], ro='1')
    remark.request('PUT', 'admin/pin/c2', url=comment()['locator']['url'], pin='1')
    original = decode_export(remark.export())
    assert original[0]['users'] and original[0]['posts'], 'Exercise real user and post metadata in recovery'
    database = Database(directory / 'moderation.sqlite')
    storage = Storage.__new__(Storage)
    storage.config, storage.database = config, database
    storage.s3, storage.bucket, storage.transfer = LocalS3(), 'local-test', None
    storage.media = directory / 'media'
    (storage.media / 'pictures').mkdir(parents=True)
    picture = storage.media / 'pictures' / 'test-image'
    picture.write_bytes(b'original image bytes')
    worker = Worker(config, database, remark, Model(), storage)
    worker.scan(); worker.process_one()
    with database.connect() as db:
        row = dict(db.execute('SELECT * FROM jobs WHERE id="c1"').fetchone())
    assert row['state'] == 'removed', row
    assert remark.get('c1', comment()['locator']['url']).get('delete')
    assert row['archive'] in storage.s3.objects
    picture.unlink()
    # Local traffic is quiescent, so only skip the public-request drain delay.
    def compare(expected, actual):
        try: compare_exports(expected, actual)
        except ValueError:
            print('Synthetic test export differences:', len(expected), len(actual))
            for before, after in zip(expected, actual):
                if before != after: print(json.dumps({'expected': before, 'actual': after}, indent=2))
            raise
    with patch('operations.time.sleep'), patch('operations.compare_exports', side_effect=compare):
        restore(worker, row['archive'])
    compare_exports(original, decode_export(remark.export()))
    assert picture.read_bytes() == b'original image bytes'
    assert not worker.maintenance.exists()
    with database.connect() as db:
        assert db.execute('SELECT approved_hash FROM jobs WHERE id="c1"').fetchone()[0]
    with storage.download(row['archive']) as tar:
        assert json.load(tar.extractfile('comment.json'))['orig'] == 'SMTP question'
    full_backup = storage.backup(remark)
    try: recover(worker, full_backup)
    except ValueError: pass
    else: raise AssertionError('Recovery must not overwrite a live store')
    # Clear this disposable test server, then exercise disaster recovery.
    remark.request('PUT', 'admin/readonly', url=records[-1]['locator']['url'], ro='0')
    remark.request('POST', 'admin/import', body=encode_export([metadata]), provider='remark')
    remark.request('GET', 'admin/wait', timeout='20s')
    picture.unlink()
    with patch('operations.time.sleep'):
        recover(worker, full_backup)
    compare_exports(original, decode_export(remark.export()))
    assert picture.read_bytes() == b'original image bytes'
    print('PASS: real admin authentication, native export, archive-before-delete, comment and full-server recovery, media, pins, bans and locked threads')
    return remark


def check_proxy(name, network, directory, build_root):
    adapted = subprocess.run(['docker', 'run', '--rm', '--env', 'ORIGIN_SECRET=integration-origin',
        '--mount', f'type=bind,src={build_root / "Caddyfile"},dst=/etc/caddy/Caddyfile,readonly',
        '--mount', f'type=bind,src={directory},dst=/proxy,readonly', CADDY,
        'caddy', 'adapt', '--config', '/etc/caddy/Caddyfile'], check=True, capture_output=True, text=True)
    production = json.loads(adapted.stdout)
    server = next(s for s in production['apps']['http']['servers'].values() if ':443' in s['listen'])
    # Exercise the exact adapted production routes on a local HTTP-only listener.
    # TLS issuance and the real CDN are launch checks; no external cert is requested.
    server['listen'] = [':8080']
    server['automatic_https'] = {'disable': True}
    server.pop('tls_connection_policies', None)
    test_config = {'admin': {'disabled': True}, 'apps': {'http': {'servers': {'test': server}}}}
    encoded = json.dumps(test_config).replace('172.29.42.3:8080', name + ':8080')
    config_path = directory / 'proxy.json'; config_path.write_text(encoded)
    (directory / 'ops').mkdir(exist_ok=True)
    proxy = name + '-proxy'
    try:
        docker('run', '--detach', '--name', proxy, '--network', network, '--publish', '127.0.0.1::8080',
               '--mount', f'type=bind,src={config_path},dst=/etc/caddy/test.json,readonly',
               '--mount', f'type=bind,src={directory / "ops"},dst=/ops,readonly',
               CADDY, 'caddy', 'run', '--config', '/etc/caddy/test.json')
        port = docker('port', proxy, '8080').split(':')[-1]
        def get(path, extra=None):
            headers = {'Host': 'comments-origin.example.com', **(extra or {})}
            request = urllib.request.Request('http://127.0.0.1:' + port + path, headers=headers)
            try: return urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError as response: return response
        for _ in range(30):
            try:
                with get('/api/v1/config?site=example') as response:
                    assert response.status == 403
                break
            except (urllib.error.URLError, ConnectionError, TimeoutError): time.sleep(.1)
        else: raise RuntimeError('Caddy test proxy unavailable')
        good = {'X-Comments-Origin': 'integration-origin'}
        with get('/api/v1/config?site=example', good) as response:
            assert response.status == 200, response.read()
            assert 'no-cache' in response.headers.get('Cache-Control', '')
        with get('/web/embed.mjs', good) as response:
            assert response.status == 200
            assert response.headers['Cache-Control'] == 'public, max-age=3600'
        for path, headers in [('/api/v1/admin/export', good), ('/api/v1/admin/import', good),
                              ('/api/v1/config', {**good, 'Authorization': 'Basic test'})]:
            with get(path, headers) as response: assert response.status == 403
        (directory / 'ops' / 'maintenance').touch()
        with get('/api/v1/config?site=example', good) as response: assert response.status == 503
        (directory / 'ops' / 'maintenance').unlink()
        (directory / 'ops' / 'disk-pressure').touch()
        with get('/api/v1/config?site=example', good) as response: assert response.status == 503
        (directory / 'ops' / 'disk-pressure').unlink()
        with get('/api/v1/config?site=example', good) as response: assert response.status == 200
        print('PASS: proxy origin gate, API/static cache headers, private admin routes, maintenance and disk-pressure gates')
    finally: subprocess.run(['docker', 'rm', '--force', proxy], capture_output=True)


def main():
    name = 'web-comments-test-' + uuid.uuid4().hex[:8]
    network, receiver, worker_image = name + '-net', name + '-receiver', name + '-worker'
    with tempfile.TemporaryDirectory(prefix='web-comments-test-') as temp:
        directory = Path(temp)
        build_root = directory / 'runtime'; build_root.mkdir()
        archive = runtime_package.build(directory / 'runtime.tar.gz')
        with tarfile.open(archive, 'r:gz') as package:
            package.extractall(build_root, filter='data')
        descriptor = {'region': 'eu-central-1', 'site_id': 'example', 'public_url': 'https://comments.example.com',
                      'origin_hostname': 'comments-origin.example.com', 'config_parameter': '/example/comments/config',
                      'backup_bucket': 'example-backups', 'host_iam_user': 'example-comments'}
        descriptor_path = directory / 'deployment.json'; descriptor_path.write_text(json.dumps(descriptor))
        config = json.loads((ROOT / 'config.example.json').read_text())
        config.update(origin_secret='a' * 48, remark_secret='integration-secret', admin_password='integration-admin',
                      webhook_secret='integration-webhook', backup_bucket='example-backups')
        runtime_renderer.render_files(config, load_deployment(descriptor_path), build_root)
        try:
            docker('network', 'create', network)
            docker('build', '--quiet', '--tag', worker_image, str(build_root))
            docker('run', '--detach', '--name', receiver, '--network', network,
                   '--mount', f'type=bind,src={ROOT / "tests" / "webhook_receiver.py"},dst=/app/receiver.py,readonly',
                   '--entrypoint', 'python', worker_image, 'receiver.py')
            docker('run', '--detach', '--name', name, '--network', network, '--publish', '127.0.0.1::8080', '--tmpfs', '/srv/var',
                   '--env', 'REMARK_URL=http://localhost:8080', '--env', 'SITE=example',
                   '--env', 'SECRET=integration-secret', '--env', 'ADMIN_PASSWD=integration-admin',
                   '--env', 'AUTH_ANON=true', '--env', 'NOTIFY_USERS=none',
                   '--env', 'NOTIFY_ADMINS=webhook', '--env', 'NOTIFY_WEBHOOK_URL=http://' + receiver + ':8090/webhook',
                   '--env', 'NOTIFY_WEBHOOK_HEADERS=Authorization:Bearer integration-webhook',
                   '--env', 'NOTIFY_WEBHOOK_TEMPLATE={"id":{{.ID | escapeJSONString}},"site":{{.Locator.SiteID | escapeJSONString}},"url":{{.Locator.URL | escapeJSONString}}}', REMARK)
            port = docker('port', name, '8080').split(':')[-1]
            remark = run('http://127.0.0.1:' + port, directory)
            created = json.loads(remark.request('POST', 'comment', body=json.dumps({
                'text': 'New comment with a private notification', 'title': 'Test',
                'locator': comment()['locator']}).encode()))
            for _ in range(30):
                ids = json.loads(docker('exec', receiver, 'python', '-c',
                    'import sqlite3,json; print(json.dumps([r[0] for r in sqlite3.connect("/tmp/notifications.sqlite").execute("SELECT id FROM jobs")]))'))
                if created['id'] in ids: break
                time.sleep(.1)
            else: raise AssertionError('Real Remark42 webhook was not durably queued')
            print('PASS: actual Remark42 notification template and authenticated webhook delivery')
            (directory / 'trusted.caddy').write_text('trusted_proxies static 192.0.2.0/24\n')
            output = docker('run', '--rm', '--env', 'ORIGIN_SECRET=integration-origin',
                '--mount', f'type=bind,src={build_root / "Caddyfile"},dst=/etc/caddy/Caddyfile,readonly',
                '--mount', f'type=bind,src={directory},dst=/proxy,readonly',
                CADDY, 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile')
            assert 'Valid configuration' in output, output
            print('PASS: production Caddy configuration')
            check_proxy(name, network, directory, build_root)
        except Exception:
            print(docker('logs', '--tail', '25', name))
            raise
        finally:
            subprocess.run(['docker', 'rm', '--force', name], capture_output=True)
            subprocess.run(['docker', 'rm', '--force', receiver], capture_output=True)
            subprocess.run(['docker', 'network', 'rm', network], capture_output=True)
            subprocess.run(['docker', 'image', 'rm', worker_image], capture_output=True)


if __name__ == '__main__': main()
