"""Verify cross-platform wheel metadata and its integrity manifest."""
import base64
import csv
import hashlib
import importlib.util
import io
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('release_package', Path(__file__).parents[1] / 'package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class WheelTests(unittest.TestCase):
    def test_windows_and_linux_metadata_produce_identical_members(self):
        members = {
            'example/__init__.py': b'answer = 42\n',
            'example.dist-info/METADATA': b'Name: example\nVersion: 1\n',
            'example.dist-info/WHEEL': b'Wheel-Version: 1.0\n',
            'example.dist-info/RECORD': b'outdated hashes\n',
        }
        windows = {name: data.replace(b'\n', b'\r\n') for name, data in members.items()}
        self.assertEqual(package.normalize_wheel_members(members), package.normalize_wheel_members(windows))

    def test_record_matches_every_normalized_member(self):
        members = package.normalize_wheel_members({
            'example/__init__.py': b'answer = 42\r\n',
            'example.dist-info/METADATA': b'Name: example\r\n',
            'example.dist-info/RECORD': b'outdated hashes\n',
        })
        rows = list(csv.reader(io.StringIO(members['example.dist-info/RECORD'].decode())))
        self.assertEqual({row[0] for row in rows}, set(members))
        for name, digest, size in rows:
            if name.endswith('/RECORD'):
                self.assertEqual((digest, size), ('', ''))
                continue
            self.assertEqual(int(size), len(members[name]))
            expected = base64.urlsafe_b64encode(hashlib.sha256(members[name]).digest()).rstrip(b'=').decode()
            self.assertEqual(digest, 'sha256=' + expected)


if __name__ == '__main__': unittest.main()
