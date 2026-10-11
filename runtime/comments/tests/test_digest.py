import datetime as dt
from email import message_from_bytes
from unittest.mock import Mock
import unittest
import digest
_build_digest = digest.build_digest
def build_digest(*args, **kwargs):
    kwargs['config'] = {'article_hosts': ['www.example.com'], 'article_path_prefix': '/journal/',
                        'site': 'example', 'public_url': 'https://comments.example.com',
                        'brand_name': 'Example Website', 'timezone': 'Europe/Amsterdam'}
    return _build_digest(*args, **kwargs)
from zoneinfo import ZoneInfo

def build_digest(*args, **kwargs):
    kwargs['config'] = {'article_hosts': ['www.example.com'], 'article_path_prefix': '/journal/',
                        'site': 'example', 'public_url': 'https://comments.example.com',
                        'brand_name': 'Example Website', 'timezone': 'Europe/Amsterdam'}
    return _build_digest(*args, **kwargs)


from digest import discussion_link
from operations import Storage

URL = 'https://www.example.com/journal/example.html'
NOW = dt.datetime(2026, 10, 6, 9, tzinfo=ZoneInfo('Europe/Amsterdam'))


def job(id_, state='review', **changes):
    return dict(id=id_, url=URL, state=state, reason='Unclear relevance', attempts=0, **changes)


def event(id_, action, detail='Reason'):
    return dict(id=id_, action=action, detail=detail)


def comment(id_, text):
    return dict(id=id_, orig=text, title='Troll farm mail servers', user={'name': 'Reader'})


class DigestTests(unittest.TestCase):
    def test_original_comments_archived_spam_and_current_decisions_are_readable(self):
        rows = [job('review'), job('removed', 'removed'), job('restored', 'keep'), job('retried', 'keep')]
        changes = [event('review', 'review'), event('removed', 'removed'), event('removed', 'removed'),
                   event('restored', 'report_spam'), event('restored', 'removed'),
                   event('restored', 'restored', 'archives/internal.tar.gz'), event('retried', 'failure', 'URLError')]
        result = build_digest(NOW, 'auto', changes, rows, {'review': comment('review', 'eee')},
                              {'removed': comment('removed', 'Make $5,000 a day!')})
        subject, plain, html = result
        self.assertIn('1 needing attention · 1 removed', subject)
        self.assertIn('eee', plain); self.assertIn('Make $5,000 a day!', html)
        self.assertIn('Reader', plain); self.assertIn('Troll farm mail servers', html)
        self.assertIn('Open discussion:', plain); self.assertIn('still visible', plain)
        self.assertNotIn('URLError', plain); self.assertNotIn('archives/internal', html)
        self.assertEqual(plain.count('Make $5,000 a day!'), 1)
        self.assertIn('1 comment restored', plain)

    def test_html_escapes_comment_author_title_and_reason(self):
        row = job('c1'); row['reason'] = '<img src=x onerror=alert(1)>'
        c = comment('c1', '<script>alert(1)</script>'); c['user']['name'] = '<svg/onload=alert(1)>'
        result = build_digest(NOW, 'auto', [event('c1', 'review')], [row], {'c1': c}, {})
        self.assertIn('&lt;script&gt;', result[2]); self.assertNotIn('<script>', result[2])
        self.assertIn('&lt;svg', result[2]); self.assertNotIn('<img src=x', result[2])
        self.assertIn('<script>alert(1)</script>', result[1])  # Plain-text alternative preserves the original.
        self.assertIsNone(discussion_link({**row, 'url': 'https://evil.example/journal/test.html'}))

    def test_quiet_and_resolved_activity_do_not_send(self):
        rows = [job('c1', 'keep'), job('old-review')]
        changes = [event('c1', 'failure', 'URLError'), event('c1', 'restored'),
                   event(None, 'storage', '{"level":"ok"}')]
        self.assertIsNone(build_digest(NOW, 'auto', changes, rows, {}, {}))
        self.assertIsNone(build_digest(NOW, 'auto', [], rows, {}, {}))

    def test_missing_comment_text_preserves_actionable_notice(self):
        result = build_digest(NOW, 'auto', [event('c1', 'review')], [job('c1')], {}, {})
        self.assertIn('Original text could not be loaded', result[1])
        self.assertIn('Open discussion:', result[1])

    def test_service_storage_history_is_summarized(self):
        changes = [event('c1', 'review'), event(None, 'storage', '{"level":"critical","free_bytes":3}'),
                   event(None, 'storage', '{"level":"ok","free_bytes":999}')]
        result = build_digest(NOW, 'auto', changes, [job('c1')], {}, {})
        self.assertIn('Storage is healthy again', result[1]); self.assertNotIn('free_bytes', result[1])
        self.assertNotIn('critical', result[1])

    def test_recovered_service_tasks_do_not_send_old_failures(self):
        changes = [event(None, 'failure', 'scan: HTTPError'), event(None, 'failure', 'backup: URLError')]
        self.assertIsNone(build_digest(NOW, 'auto', changes, [], {}, {}, {'scan': True, 'backup': True}))
        result = build_digest(NOW, 'auto', changes, [], {}, {}, {'scan': True, 'backup': False})
        self.assertIn('backup task reported a problem', result[1])
        self.assertNotIn('comment sweep', result[1])

    def test_email_contains_plain_text_and_html_without_changing_recipient(self):
        storage = Storage.__new__(Storage); storage.config = {'email_from': 'comments@example.com', 'digest_to': 'owner@example.com'}
        storage.ses = Mock()
        storage.email('Review comments', 'Original plain text', html='<p>Readable HTML</p>')
        call = storage.ses.send_raw_email.call_args.kwargs
        mail = message_from_bytes(call['RawMessage']['Data'])
        self.assertEqual(call['Destinations'], ['owner@example.com'])
        self.assertEqual(mail.get_content_type(), 'multipart/alternative')
        self.assertEqual([p.get_content_type() for p in mail.get_payload()], ['text/plain', 'text/html'])


if __name__ == '__main__': unittest.main()
