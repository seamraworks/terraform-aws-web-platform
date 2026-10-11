import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest

from web_platform_moderation import SQLiteLedger, Pricing
from moderator import BudgetExhausted, Database

spec = importlib.util.spec_from_file_location('storage_guard', Path(__file__).resolve().parents[1] / 'storage-guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class StorageTests(unittest.TestCase):
    def test_capacity_and_inode_thresholds_and_reopening_headroom(self):
        for free, files_free, paused, expected in [
            (5, 25, False, 'ok'), (4, 25, False, 'warning'),
            (2, 25, False, 'critical'), (3, 25, True, 'critical'),
            (3.5, 25, True, 'warning'), (5, 20, False, 'warning'),
            (5, 10, False, 'critical'), (5, 15, True, 'critical'),
            (5, 25, True, 'ok')]:
            with self.subTest(free=free, files_free=files_free, paused=paused):
                report = guard.evaluate(20 * guard.GIB, free * guard.GIB, 100, files_free, paused)
                self.assertEqual(report['level'], expected)
        self.assertEqual(guard.evaluate(2 * guard.GIB, .9 * guard.GIB, 100, 99)['level'], 'critical')

    def test_guard_recovers_its_flag_without_reopening_owner_maintenance(self):
        with tempfile.TemporaryDirectory() as directory:
            ops = Path(directory)
            (ops / 'maintenance').touch()
            guard.publish(ops, {'level': 'critical'})
            self.assertTrue((ops / 'disk-pressure').exists())
            self.assertEqual(json.loads((ops / 'disk-health.json').read_text())['level'], 'critical')
            guard.publish(ops, {'level': 'ok'})
            self.assertFalse((ops / 'disk-pressure').exists())
            self.assertTrue((ops / 'maintenance').exists())

    def test_history_retention_preserves_deduplication_approvals_and_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / 'moderation.sqlite')
            db.enqueue('owner-kept', 'https://www.example.com/journal/test.html', 'body-hash')
            SQLiteLedger(db.path, Pricing(.1,.5)).reserve(b'hello', .002, 1024)
            now = time.time()
            with db.connect() as conn:
                conn.execute("UPDATE jobs SET state='keep',approved_hash=hash")
                conn.executemany('INSERT INTO audit(at,id,action,detail) VALUES(?,?,?,?)',
                    [(now, 'owner-kept', 'failure', 'test')] * 10020 + [(now - 31 * 86400, None, 'old', 'expired')])
                conn.execute("INSERT INTO spending(month,reserved) VALUES('2000-01',1000)")
                conn.commit()
            db.setting('digest_cursor', 10010)
            db.prune_history()
            with db.connect() as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM audit').fetchone()[0], 10000)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit WHERE action='old'").fetchone()[0], 0)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM spending').fetchone()[0], 1)
                self.assertEqual(conn.execute('SELECT approved_hash FROM jobs').fetchone()[0], 'body-hash')
            self.assertEqual(db.setting('digest_cursor'), '10010')
            with self.assertRaises(BudgetExhausted): SQLiteLedger(db.path, Pricing(.1,.5)).reserve(b'hello', .002, 1024)
            db.audit(None, 'new', 'After cleanup')
            with db.connect() as conn:
                self.assertGreater(conn.execute("SELECT n FROM audit WHERE action='new'").fetchone()[0], 10021)


if __name__ == '__main__': unittest.main()
