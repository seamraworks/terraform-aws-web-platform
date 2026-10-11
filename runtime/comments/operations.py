"""Off-host archives, backups, digest delivery and guarded native recovery."""
import contextlib
import copy
import datetime as dt
from email.message import EmailMessage
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sqlite3
import tarfile
import tempfile
import time
import uuid

from moderator import decode_export, fingerprint, timestamp


def encode_export(records):
    return ("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n").encode()


def merge_archive(records, archived, site):
    """Never feed a single archived comment to Remark42's destructive importer."""
    target = archived["id"]
    if archived["locator"].get("site") != site or archived.get("delete"):
        raise ValueError("Archive does not contain a live comment from this site")
    if archived.get("pid") and archived["pid"] not in {r["id"] for r in records[1:]}:
        raise ValueError("Parent comment is missing; recover the parent first")
    merged, found = [records[0]], False
    for record in records[1:]:
        if record["id"] == target:
            if not record.get("delete"):
                raise ValueError("Refusing to overwrite an existing live comment")
            merged.append(archived); found = True
        else: merged.append(record)
    if not found: merged.append(archived)
    return merged


def compare_exports(expected, actual):
    # Remark42 explicitly marks every native-imported record as imported.
    def normalize(records):
        return {r["id"]: {k: v for k, v in r.items() if k != "imported"} for r in records[1:]}
    expected_meta, actual_meta = copy.deepcopy(expected[0]), copy.deepcopy(actual[0])
    actual_users = {u['id']: u for u in actual_meta.get('users', [])} if isinstance(actual_meta.get('users'), list) else {}
    for user in expected_meta.get('users', []) if isinstance(expected_meta.get('users'), list) else []:
        other = actual_users.get(user['id'], {})
        before, after = user.get('blocked', {}), other.get('blocked', {})
        if before.get('status') and after.get('status') and before.get('until') and after.get('until'):
            # Native import converts an absolute ban expiry to TTL and back;
            # retain the expiry to within one second, not nanosecond identity.
            if abs(timestamp(before['until']) - timestamp(after['until'])) < 1:
                after['until'] = before['until']
    if expected_meta != actual_meta or normalize(expected) != normalize(actual):
        raise ValueError("Recovery verification failed; maintenance remains enabled")


def import_snapshot(remark, records):
    # v1.17.1 retains post locks while clearing comment buckets. Importing into
    # those locked posts fails partway through. Public traffic is already paused;
    # temporarily unlock precisely the saved locked posts, then restore metadata.
    for post in records[0].get("posts", []):
        if post.get("read_only"):
            remark.request("PUT", "admin/readonly", url=post["url"], ro="0")
    remark.request("POST", "admin/import", body=encode_export(records), provider="remark")
    remark.request("GET", "admin/wait", timeout="90s")
    # Reapply explicitly before checking the complete native export. The wait
    # endpoint returns 200 even if the asynchronous import failed.
    for post in records[0].get("posts", []):
        remark.request("PUT", "admin/readonly", url=post["url"], ro="1" if post.get("read_only") else "0")
    compare_exports(records, decode_export(remark.export()))


class Storage:
    def __init__(self, config, database):
        import boto3
        from boto3.s3.transfer import TransferConfig
        from botocore.config import Config
        self.config, self.database = config, database
        self.session = boto3.Session(region_name=config["region"],
            aws_access_key_id=config["aws_access_key_id"], aws_secret_access_key=config["aws_secret_access_key"])
        options = Config(retries={"max_attempts": 3}, connect_timeout=10, read_timeout=60)
        self.s3 = self.session.client("s3", config=options)
        self.ses = self.session.client("ses", config=options)
        self.cloudwatch = self.session.client("cloudwatch", config=options)
        self.transfer = TransferConfig(max_concurrency=1, use_threads=False)
        self.bucket = config["backup_bucket"]
        self.media = Path(config.get("remark_data", "/remark-data"))

    def heartbeat(self, healthy):
        self.cloudwatch.put_metric_data(Namespace=self.config.get("metric_namespace", "WebPlatform/Comments"), MetricData=[{
            "MetricName": "Healthy", "Dimensions": [{"Name": "Site", "Value": self.config["site"]}],
            "Value": 1 if healthy else 0, "Unit": "Count",
        }])

    def email(self, subject, body, html=None):
        if not self.config.get("digest_to"): return
        message = EmailMessage()
        message["From"] = self.config["email_from"]
        message["To"] = self.config["digest_to"]
        message["Subject"] = subject
        message.set_content(body)
        if html is not None: message.add_alternative(html, subtype="html")
        self.ses.send_raw_email(Source=message["From"], Destinations=[message["To"]],
                                RawMessage={"Data": message.as_bytes()})

    def _bundle(self, prefix, files):
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y/%m/%d/%H%M%S")
        key = f"{prefix}/{stamp}-{uuid.uuid4().hex}.tar.gz"
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle.tar.gz"
            with tarfile.open(bundle, mode="w:gz") as tar:
                for name, data in files.items():
                    entry = tarfile.TarInfo(name)
                    entry.size, entry.mode = len(data), 0o600
                    tar.addfile(entry, io.BytesIO(data))
                # A media snapshot also preserves uploaded images whose filesystem
                # names aren't part of the public comment API. Never archive the live DB.
                for folder in ("avatars", "pictures"):
                    root = self.media / folder
                    if root.exists():
                        for path in root.rglob("*"):
                            if path.is_symlink(): raise ValueError("Symlink in media directory")
                            if path.is_file(): tar.add(path, arcname="media/" + path.relative_to(self.media).as_posix(), recursive=False)
            if bundle.stat().st_size > 64 * 1024 * 1024:
                raise ValueError("Archive exceeds small-server limit; manual review required")
            self.s3.upload_file(str(bundle), self.bucket, key,
                                ExtraArgs={"ServerSideEncryption": "AES256"}, Config=self.transfer)
        return key

    def archive(self, comment, decision):
        return self._bundle("archives", {
            "comment.json": json.dumps(comment).encode(),
            "decision.json": json.dumps(decision).encode(),
        })

    def backup(self, remark):
        raw = remark.export()
        decode_export(raw)  # refuse truncated/invalid backups
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / "moderation.sqlite"
            target = sqlite3.connect(snapshot)
            with self.database.connect() as source: source.backup(target)
            target.close()
            state = snapshot.read_bytes()
        key = self._bundle("backups", {"comments.jsonl": raw, "moderation.sqlite": state,
            "manifest.json": json.dumps({"site": self.config["site"], "remark_version": "v1.17.1",
                                         "sha256": hashlib.sha256(raw).hexdigest()}).encode()})
        # The daily successful-backup timestamp is also a cheap off-host heartbeat.
        self.database.audit(None, "backup", key)
        return key

    @contextlib.contextmanager
    def download(self, key):
        if not key.startswith(("archives/", "backups/")) or ".." in key:
            raise ValueError("Invalid archive key")
        obj = self.s3.get_object(Bucket=self.bucket, Key=key)
        if obj["ContentLength"] > 64 * 1024 * 1024:
            obj["Body"].close()
            raise ValueError("Archive exceeds small-server limit")
        with tempfile.NamedTemporaryFile(suffix=".tar.gz") as temp:
            try:
                for part in obj["Body"].iter_chunks(65536): temp.write(part)
            finally: obj["Body"].close()
            temp.flush(); temp.seek(0)
            with tarfile.open(fileobj=temp, mode="r:gz") as tar:
                total = 0
                for member in tar.getmembers():
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or ".." in path.parts or not member.isfile():
                        raise ValueError("Unsafe archive entry")
                    total += member.size
                    if total > 128 * 1024 * 1024: raise ValueError("Expanded archive too large")
                yield tar


def restore(worker, archive):
    """Caller holds the operation lock. Failure deliberately leaves writes paused."""
    with worker.storage.download(archive) as tar:
        comment = json.load(tar.extractfile("comment.json"))
        decision = json.load(tar.extractfile("decision.json"))
        if fingerprint(comment) != decision["hash"]: raise ValueError("Archive integrity mismatch")
        worker.validate(comment["id"], comment["locator"]["url"])
        worker.maintenance.parent.mkdir(parents=True, exist_ok=True)
        worker.maintenance.touch()
        worker.db.audit(comment["id"], "maintenance", "Recovery started; public requests paused")
        time.sleep(31)  # drain bounded in-flight public mutations before fresh export
        current = decode_export(worker.remark.export())
        merged = merge_archive(current, comment, worker.config["site"])
        rollback_key = worker.storage.backup(worker.remark)
        worker.db.audit(comment["id"], "recovery_backup", rollback_key)
        import_snapshot(worker.remark, merged)
        # Restore absent media only; never replace newer files from current users.
        for member in tar.getmembers():
            if not member.name.startswith(("media/avatars/", "media/pictures/")): continue
            destination = worker.storage.media / member.name.removeprefix("media/")
            if not destination.resolve().is_relative_to(worker.storage.media.resolve()):
                raise ValueError("Media path escaped its root")
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as output: output.write(tar.extractfile(member).read())
        digest = fingerprint(comment)
        worker.db.enqueue(comment["id"], comment["locator"]["url"], digest)
        worker.finish(comment["id"], digest, "keep", "Restored by owner", archive)
        with worker.db.connect() as db:
            db.execute("UPDATE jobs SET approved_hash=? WHERE id=?", (digest, comment["id"])); db.commit()
        worker.db.audit(comment["id"], "restored", archive)
        worker.maintenance.unlink()
        print("Restored and verified. Rollback backup: " + rollback_key)


def recover(worker, archive, replace_existing=False):
    """Restore a full backup on an empty host, or explicitly roll back while paused.

The resident worker must be stopped; the comments wrapper enforces that.
"""
    if not archive.startswith('backups/'):
        raise ValueError('Full recovery requires a backups/ archive')
    current = decode_export(worker.remark.export())
    if len(current) > 1 and not (replace_existing and worker.maintenance.exists()):
        raise ValueError('Recovery requires an empty store, or --replace-existing while maintenance is already enabled')
    with worker.storage.download(archive) as tar:
        manifest = json.load(tar.extractfile('manifest.json'))
        raw = tar.extractfile('comments.jsonl').read()
        if manifest['site'] != worker.config['site'] or hashlib.sha256(raw).hexdigest() != manifest['sha256']:
            raise ValueError('Backup site or checksum mismatch')
        records = decode_export(raw)
        if any(c['locator']['site'] != worker.config['site'] for c in records[1:]):
            raise ValueError('Backup contains a different site')
        worker.maintenance.parent.mkdir(parents=True, exist_ok=True)
        worker.maintenance.touch()
        time.sleep(31)
        import_snapshot(worker.remark, records)
        for member in tar.getmembers():
            if not member.name.startswith(('media/avatars/', 'media/pictures/')): continue
            destination = worker.storage.media / member.name.removeprefix('media/')
            if not destination.resolve().is_relative_to(worker.storage.media.resolve()):
                raise ValueError('Media path escaped its root')
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open('xb') as output: output.write(tar.extractfile(member).read())
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / 'moderation.sqlite'
            snapshot.write_bytes(tar.extractfile('moderation.sqlite').read())
            with contextlib.closing(sqlite3.connect(snapshot)) as source:
                if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Moderation backup is corrupt')
                for table in ('jobs', 'spending', 'settings', 'audit'):
                    source.execute('SELECT COUNT(*) FROM ' + table).fetchone()
                with worker.db.connect() as target: source.backup(target.db)
        for name in ('last_scan', 'last_backup', 'last_heartbeat'):
            worker.db.setting(name, 0)
        worker.db.audit(None, 'recovered', archive)
        worker.maintenance.unlink()
        print('Full backup restored and verified. Review the recovered moderation state before enabling automatic removal.')
