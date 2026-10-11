import copy
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from moderator import BudgetExhausted, Database, ModerationAdapter, Worker, fingerprint, webhook_handler
from operations import compare_exports, encode_export, merge_archive

URL = 'https://www.example.com/journal/example.html'


def comment(id_='c1', **changes):
    value = dict(id=id_, pid='', text='<p>SMTP question</p>', orig='SMTP question',
                 time='2026-01-01T12:00:00Z', user={'id': 'google_reader', 'name': 'Reader'},
                 locator={'site': 'example', 'url': URL}, title='Mail servers')
    value.update(changes)
    return value


class Remark:
    base = 'http://remark:8080'
    def __init__(self):
        self.records = {'c1': comment()}
        self.deleted = []

    def get(self, id_, url): return copy.deepcopy(self.records[id_])
    def export(self): return encode_export([{'version': 1}, *self.records.values()])
    def delete(self, id_, url):
        self.deleted.append(id_)
        self.records[id_].update(delete=True, orig='', text='')


class Storage:
    def __init__(self): self.archived, self.emails, self.before_archive = [], [], None
    def archive(self, record, decision):
        if self.before_archive: self.before_archive()
        self.archived.append(copy.deepcopy(record))
        return 'archives/test.tar.gz'
    def email(self, subject, body, html=None): self.emails.append(body)


class Model:
    def __init__(self, decision='spam'): self.calls, self.decision = 0, decision
    def classify(self, *_):
        self.calls += 1
        return {'decision': self.decision, 'reason': 'Classification explanation'}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / 'moderation.sqlite')
        self.remark, self.storage, self.model = Remark(), Storage(), Model()
        self.config = {'site': 'example', 'mode': 'auto', 'webhook_secret': 'test-secret',
                       'ops_dir': self.temp.name, 'public_url': 'https://comments.example.com', 'timezone': 'Europe/Amsterdam', 'article_hosts': ['www.example.com'], 'article_path_prefix': '/journal/', 'admin_ids': ['google_owner']}
        self.worker = Worker(self.config, self.db, self.remark, self.model, self.storage)
        (Path(self.temp.name) / 'disk-health.json').write_text(json.dumps({'level': 'ok', 'checked_at': time.time()}))

    def row(self):
        with self.db.connect() as db: return dict(db.execute('SELECT * FROM jobs WHERE id="c1"').fetchone())

    def test_scan_and_duplicate_webhooks_classify_once(self):
        self.worker.scan()
        self.db.enqueue('c1', URL)
        self.worker.process_one()
        self.db.enqueue('c1', URL)
        self.worker.scan()
        self.assertFalse(self.worker.process_one())
        self.assertEqual(self.model.calls, 1)
        self.assertEqual(self.row()['state'], 'removed')
        self.assertEqual(self.storage.archived[0]['orig'], 'SMTP question')
        self.assertEqual(self.row()['archive'], 'archives/test.tar.gz')

    def test_report_mode_and_uncertainty_retain_comments(self):
        self.config['mode'] = 'report'
        self.worker.scan(); self.worker.process_one()
        self.assertEqual(self.row()['state'], 'report_spam')
        self.model.decision = 'review'
        self.worker.scan(retry=True); self.worker.process_one()
        self.assertEqual(self.row()['state'], 'review')
        self.assertEqual(self.remark.deleted, [])
        self.assertEqual(self.storage.archived, [])

    def test_storage_failure_cannot_delete(self):
        def fail(): raise OSError('S3 unavailable')
        self.storage.before_archive = fail
        self.worker.scan(); self.worker.process_one()
        self.assertEqual(self.remark.deleted, [])
        self.assertEqual(self.row()['state'], 'pending')
        self.assertEqual(self.row()['attempts'], 1)
        self.assertEqual(self.row()['reason'], 'OSError')

    def test_edit_during_archive_requires_another_review(self):
        self.storage.before_archive = lambda: self.remark.records['c1'].update(orig='Relevant revised text')
        self.worker.scan(); self.worker.process_one()
        self.assertEqual(self.remark.deleted, [])
        self.assertEqual(self.row()['hash'], fingerprint(self.remark.records['c1']))
        self.assertEqual(self.row()['state'], 'pending')

    def test_hourly_sweep_notices_edits_but_ignores_votes(self):
        self.model.decision = 'keep'
        self.worker.scan(); self.worker.process_one()
        self.remark.records['c1']['score'] = 9
        self.worker.scan(); self.assertFalse(self.worker.process_one())
        self.remark.records['c1']['orig'] = 'An edited comment'
        self.worker.scan(); self.worker.process_one()
        self.assertEqual(self.model.calls, 2)

    def test_invented_thread_does_not_stop_the_sweep(self):
        self.remark.records['outside'] = comment('outside', locator={'site': 'example', 'url': 'https://evil.example/elsewhere'})
        self.worker.scan(); self.worker.process_one()
        self.assertEqual(self.row()['state'], 'removed')
        self.worker.scan()
        with self.db.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM jobs WHERE id="outside"').fetchone()[0], 'review')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM audit WHERE id="outside"').fetchone()[0], 1)

    def test_owner_and_recent_comments_do_not_reach_model(self):
        self.remark.records['c1']['user']['id'] = 'google_owner'
        self.worker.scan(); self.worker.process_one()
        self.assertEqual(self.model.calls, 0)
        self.remark.records['c1']['user']['id'] = 'google_reader'
        self.remark.records['c1']['time'] = dt.datetime.now(dt.timezone.utc).isoformat()
        self.worker.scan(); self.assertFalse(self.worker.process_one())
        self.assertEqual(self.model.calls, 0)

    def test_maintenance_and_owner_approval_are_respected(self):
        self.worker.scan()
        self.worker.maintenance.touch()
        self.assertFalse(self.worker.process_one())
        self.worker.maintenance.unlink()
        with self.db.connect() as db:
            db.execute('UPDATE jobs SET approved_hash=hash'); db.commit()
        self.worker.process_one()
        self.assertEqual(self.model.calls, 0)
        self.assertEqual(self.row()['state'], 'keep')

    def test_model_404_is_retryable_not_a_missing_comment(self):
        with patch.object(self.model, 'classify', side_effect=urllib.error.HTTPError(
                'https://api.openai.com/v1/responses', 404, 'Model unavailable', {}, None)):
            self.worker.scan(); self.worker.process_one()
        self.assertEqual(self.row()['state'], 'pending')
        self.assertEqual(self.remark.deleted, [])

    def test_missing_parent_does_not_mark_live_reply_as_gone(self):
        self.remark.records['c1']['pid'] = 'missing-parent'
        get = self.remark.get
        def read(id_, url):
            if id_ == 'missing-parent':
                raise urllib.error.HTTPError('http://remark:8080/api/v1/id/missing-parent?site=example', 404, 'Missing', {}, None)
            return get(id_, url)
        with patch.object(self.remark, 'get', side_effect=read):
            self.worker.scan(); self.worker.process_one()
        self.assertEqual(self.row()['state'], 'pending')

    def test_scheduled_backup_failure_still_reviews_and_publishes_unhealthy(self):
        self.model.decision = 'keep'
        heartbeats = []
        self.storage.heartbeat = heartbeats.append
        self.storage.backup = lambda _: (_ for _ in ()).throw(OSError())
        with patch.object(self.worker, 'digest'):
            self.worker.tick()
        self.assertEqual(self.row()['state'], 'keep')
        self.assertEqual(heartbeats, [False])
        self.assertIsNotNone(self.db.setting('last_scan'))
        self.assertIsNone(self.db.setting('last_backup'))

    def test_successful_backups_do_not_generate_daily_email(self):
        self.db.audit(None, 'backup', 'backups/test.tar.gz')
        self.db.audit('c1', 'keep', 'Relevant comment')
        class Noon(dt.datetime):
            @classmethod
            def now(cls, tz=None): return cls(2026, 10, 3, 12, tzinfo=dt.timezone.utc)
        with patch('moderator.dt.datetime', Noon): self.worker.digest()
        self.assertEqual(self.storage.emails, [])

    def test_disk_warning_and_stale_monitor_raise_failure_heartbeat(self):
        self.model.decision = 'keep'
        heartbeats = []
        self.storage.heartbeat = heartbeats.append
        self.storage.backup = lambda _: 'backups/test.tar.gz'
        for level, age, healthy in [('ok', 0, True), ('warning', 0, False), ('ok', 181, False)]:
            (Path(self.temp.name) / 'disk-health.json').write_text(json.dumps({'level': level, 'checked_at': time.time() - age}))
            self.db.setting('last_heartbeat', 0)
            with patch.object(self.worker, 'digest'): self.worker.tick()
            self.assertEqual(heartbeats[-1], healthy)

    def test_disk_pause_stops_work_without_discarding_queue(self):
        self.worker.scan()
        self.worker.disk_pressure.touch()
        self.assertFalse(self.worker.process_one())
        self.assertEqual(self.row()['state'], 'pending')
        self.assertEqual(self.model.calls, 0)
        self.worker.disk_pressure.unlink()
        self.assertTrue(self.worker.process_one())
        self.assertEqual(self.row()['state'], 'removed')

    def test_failed_digest_retains_cursor_for_retry(self):
        self.worker.scan()
        self.worker.finish('c1', fingerprint(self.remark.records['c1']), 'review', 'Uncertain')
        class Noon(dt.datetime):
            @classmethod
            def now(cls, tz=None): return cls(2026, 10, 3, 12, tzinfo=dt.timezone.utc)
        with patch('moderator.dt.datetime', Noon):
            with patch.object(self.storage, 'email', side_effect=OSError()):
                with self.assertRaises(OSError): self.worker.digest()
            self.assertIsNone(self.db.setting('digest_cursor'))
            self.worker.digest()
        self.assertEqual(len(self.storage.emails), 1)

    def test_retry_limit_retains_comment_for_owner(self):
        self.worker.scan()
        with patch.object(self.model, 'classify', side_effect=TimeoutError()):
            for _ in range(5):
                with self.db.connect() as db: db.execute('UPDATE jobs SET due=0'); db.commit()
                self.worker.process_one()
        self.assertEqual(self.row()['state'], 'failed')
        self.assertEqual(self.remark.deleted, [])

    def test_webhook_authentication_scope_and_durability(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), webhook_handler(self.worker))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        def send(payload, secret='test-secret'):
            request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/webhook',
                data=json.dumps(payload).encode(), headers={'Authorization': 'Bearer ' + secret})
            return urllib.request.urlopen(request)
        payload = {'id': 'c1', 'url': URL, 'site': 'example'}
        for changed, secret in [(payload, 'wrong'), ({**payload, 'site': 'other'}, 'test-secret'),
                                 ({**payload, 'url': 'https://evil.example/'}, 'test-secret')]:
            with self.assertRaises(urllib.error.HTTPError): send(changed, secret)
        with send(payload) as response: self.assertEqual(response.status, 202)
        with send(payload) as response: self.assertEqual(response.status, 202)
        with self.db.connect() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)
        self.worker.disk_pressure.touch()
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            send({**payload, 'id': 'c2'})
        self.assertEqual(rejected.exception.code, 503)
        with self.db.connect() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)



class RecoveryTests(unittest.TestCase):
    def test_merge_preserves_other_threads_and_metadata(self):
        archived = comment()
        records = [{'version': 1, 'users': {'blocked': ['bad-user']}, 'posts': {'readonly': ['url']}},
                   comment(delete=True, orig='', text=''), comment('c2', pid='c1'),
                   comment('c3', locator={'site': 'example', 'url': URL.replace('example', 'another')})]
        merged = merge_archive(records, archived, 'example')
        self.assertEqual(merged[0], records[0])
        self.assertEqual(merged[1], archived)
        self.assertEqual(merged[2:], records[2:])
        compare_exports(merged, [merged[0], *[{**c, 'imported': True} for c in merged[1:]]])
        with self.assertRaises(ValueError): compare_exports(merged, merged[:-1])
        with self.assertRaises(ValueError): merge_archive(merged, archived, 'example')
        with self.assertRaises(ValueError): merge_archive(records, archived, 'wrong-site')
        with self.assertRaises(ValueError): merge_archive(records, comment('orphan', pid='missing'), 'example')


if __name__ == '__main__': unittest.main()
