"""Small, conservative Remark42 moderator. Only the worker holds admin credentials.

Public webhooks are deliberately unnecessary: Remark42 calls this on the private
container network. SQLite is the durable queue, audit trail and spending ledger.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

from web_platform_moderation import (
    ModerationRequest, BudgetExhausted, ProviderError, create_provider,
)


def timestamp(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def fingerprint(comment):
    # Votes do not cause another model call; text, author and thread context do.
    value = [comment.get("orig") or comment.get("text", ""), comment.get("pid", ""),
             comment.get("user", {}).get("id"), comment.get("locator"), comment.get("title", "")]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def load_config():
    config = json.loads(Path(os.environ.get("COMMENTS_CONFIG", "/config/config.json")).read_text())
    if config.get("mode", "report") not in {"report", "auto"}:
        raise ValueError("mode must be report or auto")
    if not config.get("webhook_secret") or not config.get("admin_password"):
        raise ValueError("Webhook and Remark42 credentials are required")
    if not config.get("article_hosts") or not config.get("article_path_prefix", "").startswith("/"):
        raise ValueError("Configure the allowed article hosts and path prefix")
    return config


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, url TEXT NOT NULL, hash TEXT,
                    state TEXT NOT NULL DEFAULT 'pending', due REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '',
                    archive TEXT, approved_hash TEXT);
                CREATE TABLE IF NOT EXISTS audit (
                    n INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                    id TEXT, action TEXT NOT NULL, detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS spending (
                    n INTEGER PRIMARY KEY AUTOINCREMENT, month TEXT NOT NULL,
                    reserved INTEGER NOT NULL, actual INTEGER);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return contextlib.closing(_Connection(db))

    def enqueue(self, id_, url, digest=None, due=None, retry=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM jobs WHERE id=?", (id_,)).fetchone()
            if old is None:
                db.execute("INSERT INTO jobs(id,url,hash,due) VALUES(?,?,?,?)",
                           (id_, url, digest, due or time.time()))
            elif old["url"] != url:
                raise ValueError("Comment ID moved between threads")
            elif (digest and digest != old["hash"]) or (retry and old["state"] in {"failed", "review", "report_spam"}):
                db.execute("UPDATE jobs SET hash=?,state='pending',due=?,attempts=0,reason='',"
                           "approved_hash=NULL WHERE id=?", (digest, due or time.time(), id_))
            db.commit()

    def audit(self, id_, action, detail=""):
        with self.connect() as db:
            db.execute("INSERT INTO audit(at,id,action,detail) VALUES(?,?,?,?)",
                       (time.time(), id_, action, detail[:1000]))
            db.commit()

    def setting(self, key, value=None):
        with self.connect() as db:
            if value is not None:
                db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, str(value)))
                db.commit()
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row[0] if row else None

    def prune_history(self):
        # Keep decisions/owner approvals in jobs: deleting those would classify
        # old comments again. Only repetitive operational history expires.
        previous_month = (dt.datetime.now(dt.timezone.utc).replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
        with self.connect() as db:
            db.execute("DELETE FROM audit WHERE at<?", (time.time() - 30 * 86400,))
            db.execute("DELETE FROM audit WHERE n<COALESCE("
                       "(SELECT n FROM audit ORDER BY n DESC LIMIT 1 OFFSET 9999),0)")
            db.execute("DELETE FROM spending WHERE month<?", (previous_month,))
            db.commit()
            # Reuse freed database pages instead of a space-hungry VACUUM copy.
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")



class _Connection:
    """Closing also rolls back an unfinished transaction, including budget failures."""
    def __init__(self, db): self.db = db
    def __getattr__(self, key): return getattr(self.db, key)
    def close(self): self.db.close()


class Remark:
    def __init__(self, config):
        self.config = config
        self.base = config.get("remark_url", "http://remark:8080")
        self.auth = "Basic " + base64.b64encode(("admin:" + config["admin_password"]).encode()).decode()

    def request(self, method, path, url=None, body=None, **params):
        query = {"site": self.config["site"], **params}
        if url is not None: query["url"] = url
        request = urllib.request.Request(self.base + "/api/v1/" + path + "?" + urllib.parse.urlencode(query),
                                         data=body, method=method,
                                         headers={"Authorization": self.auth, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read(32 * 1024 * 1024 + 1)

    def get(self, id_, url):
        return json.loads(self.request("GET", "id/" + urllib.parse.quote(id_, safe=""), url))

    def export(self):
        return self.request("GET", "admin/export", mode="stream")

    def delete(self, id_, url):
        self.request("DELETE", "admin/comment/" + urllib.parse.quote(id_, safe=""), url)


def decode_export(raw):
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("Export exceeds this deployment's memory budget")
    decoder, records, source = json.JSONDecoder(), [], raw.decode()
    while source.strip():
        source = source.lstrip()
        value, end = decoder.raw_decode(source)
        records.append(value)
        source = source[end:]
    if not records or not isinstance(records[0], dict) or "version" not in records[0]:
        raise ValueError("Missing native Remark42 export metadata")
    ids = set()
    for comment in records[1:]:
        if not comment.get("id") or comment["id"] in ids or not comment.get("locator"):
            raise ValueError("Incomplete or duplicate exported comment")
        ids.add(comment["id"])
    return records


class ModerationAdapter:
    """Only relevant text/context crosses the provider boundary, never account/IP data."""
    def __init__(self, config, database):
        self.provider = create_provider(config, database.path)

    def classify(self, comment, parent=None):
        request = ModerationRequest(comment.get("orig") or comment.get("text", ""), {
            "page_title": comment.get("title", "")[:300],
            "page_url": comment["locator"]["url"],
            "parent_text": (parent or {}).get("orig") or (parent or {}).get("text", ""),
        })
        return self.provider.classify(request).to_dict()


class Worker:
    def __init__(self, config, db, remark, model, storage):
        self.config, self.db, self.remark, self.model, self.storage = config, db, remark, model, storage
        self.maintenance = Path(config.get("ops_dir", "/ops")) / "maintenance"
        self.disk_pressure = self.maintenance.parent / "disk-pressure"

    def paused(self):
        return self.maintenance.exists() or self.disk_pressure.exists()

    def storage_status(self):
        try:
            report = json.loads((self.maintenance.parent / "disk-health.json").read_text())
            if report["level"] not in {"ok", "warning", "critical"} or not 0 <= time.time() - report["checked_at"] <= 180:
                raise ValueError("Stale disk monitor")
            return report
        except (OSError, ValueError, KeyError, TypeError):
            return {"level": "unknown", "reason": "Host disk monitor missing or more than three minutes old"}

    def validate(self, id_, url):
        parsed = urllib.parse.urlsplit(url)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", id_):
            raise ValueError("Invalid comment ID")
        if (parsed.scheme != "https" or parsed.netloc not in self.config["article_hosts"] or
                not parsed.path.startswith(self.config["article_path_prefix"]) or parsed.query or parsed.fragment):
            raise ValueError("Unexpected article URL")

    def scan(self, retry=False):
        for comment in decode_export(self.remark.export())[1:]:
            if comment.get("delete"): continue
            url = comment["locator"]["url"]
            if comment["locator"].get("site") != self.config["site"]:
                raise ValueError("Unexpected site in export")
            try: self.validate(comment["id"], url)
            except ValueError:
                # The public API can receive comments for invented URLs. One
                # such record must not stop moderation of every real article.
                digest = fingerprint(comment)
                with self.db.connect() as db:
                    previous = db.execute("SELECT hash FROM jobs WHERE id=?", (comment["id"],)).fetchone()
                if previous is None or previous["hash"] != digest:
                    self.db.enqueue(comment["id"], url, digest)
                    self.finish(comment["id"], digest, "review", "Unexpected article URL; manual review required")
                continue
            self.db.enqueue(comment["id"], url, fingerprint(comment),
                            timestamp(comment["time"]) + 310, retry)

    def finish(self, id_, digest, decision, reason, archive=None):
        with self.db.connect() as db:
            db.execute("UPDATE jobs SET state=?,hash=?,reason=?,archive=COALESCE(?,archive),attempts=0 WHERE id=?",
                       (decision, digest, reason, archive, id_))
            db.commit()
        self.db.audit(id_, decision, reason)

    def remove(self, comment, reason):
        id_, url = comment["id"], comment["locator"]["url"]
        digest = fingerprint(comment)
        current = self.remark.get(id_, url)
        if current.get("delete"):
            self.finish(id_, digest, "gone", "Already removed")
            return
        if fingerprint(current) != digest:
            self.db.enqueue(id_, url, fingerprint(current), time.time() + 310)
            return
        # Native full record and media are saved OFF the instance before deletion.
        archive = self.storage.archive(current, {"reason": reason, "policy": self.config.get("policy_id", "spam-1"),
                                                "model": self.config.get("model", ""), "provider": self.config.get("moderation_provider", "none"), "hash": digest})
        with self.db.connect() as db:
            db.execute("UPDATE jobs SET archive=? WHERE id=?", (archive, id_))
            db.commit()
        fresh = self.remark.get(id_, url)
        if fingerprint(fresh) != digest or fresh.get("delete"):
            self.db.enqueue(id_, url, fingerprint(fresh), time.time() + 310, retry=True)
            return
        self.remark.delete(id_, url)
        if not self.remark.get(id_, url).get("delete"):
            raise RuntimeError("Removal could not be verified")
        self.finish(id_, digest, "removed", reason, archive)

    def process_one(self):
        if self.paused(): return False
        with self.db.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE state='pending' AND due<=? ORDER BY due LIMIT 1",
                             (time.time(),)).fetchone()
        if row is None: return False
        id_, url = row["id"], row["url"]
        try:
            comment = self.remark.get(id_, url)
            self.validate(id_, url)
            if comment.get("id") != id_ or comment.get("locator") != {"site": self.config["site"], "url": url}:
                raise ValueError("Comment response identity mismatch")
            digest = fingerprint(comment)
            if comment.get("delete"):
                self.finish(id_, digest, "removed" if row["archive"] else "gone",
                            "Removal confirmed after retry" if row["archive"] else "Already removed")
                return True
            if comment.get("user", {}).get("id") in self.config.get("admin_ids", []):
                self.finish(id_, digest, "keep", "Owner comment")
                return True
            due = timestamp(comment["time"]) + 310
            if due > time.time():
                with self.db.connect() as db:
                    db.execute("UPDATE jobs SET due=? WHERE id=?", (due, id_)); db.commit()
                return True
            if row["approved_hash"] == digest:
                self.finish(id_, digest, "keep", "Kept by owner")
                return True
            parent = self.remark.get(comment["pid"], url) if comment.get("pid") else None
            result = self.model.classify(comment, parent)
            self.db.audit(id_, "provider", json.dumps({k: result.get(k, "") for k in ("provider", "model", "policy_id")}))
            if self.paused(): return False
            if result["decision"] == "spam" and self.config.get("mode", "report") == "auto":
                self.remove(comment, result["reason"])
            else:
                self.finish(id_, digest, "report_spam" if result["decision"] == "spam" else result["decision"], result["reason"])
        except BudgetExhausted:
            today = dt.datetime.now(dt.timezone.utc)
            reset = (today.replace(day=28) + dt.timedelta(days=4)).replace(day=1, hour=0, minute=1, second=0)
            with self.db.connect() as db:
                db.execute("UPDATE jobs SET due=?,reason='Monthly API budget exhausted' WHERE id=?", (reset.timestamp(), id_))
                db.commit()
            self.db.audit(id_, "budget", "Monthly API budget exhausted; comment retained")
        except urllib.error.HTTPError as exc:
            target = self.remark.base + "/api/v1/id/" + urllib.parse.quote(id_, safe="")
            if exc.code == 404 and exc.url.split("?", 1)[0] == target:
                self.finish(id_, row["hash"], "gone", "Comment no longer exists")
            else: self.failed(row, "HTTP " + str(exc.code))
        except Exception as exc:
            self.failed(row, type(exc).__name__)
        return True

    def failed(self, row, detail):
        attempt = row["attempts"] + 1
        with self.db.connect() as db:
            db.execute("UPDATE jobs SET attempts=?,state=?,due=?,reason=? WHERE id=?",
                       (attempt, "failed" if attempt >= 5 else "pending", time.time() + min(3600, 60 * 2**attempt), detail, row["id"]))
            db.commit()
        self.db.audit(row["id"], "failure", detail + "; comment retained")

    def digest(self):
        from digest import build_digest
        now = dt.datetime.now(ZoneInfo(self.config.get("timezone", "UTC")))
        if now.hour < 9 or self.db.setting("digest_day") == now.date().isoformat(): return
        after = int(self.db.setting("digest_cursor") or 0)
        with self.db.connect() as db:
            changes = list(reversed(db.execute("SELECT * FROM audit WHERE n>? AND action NOT IN ('keep','backup','gone') ORDER BY n DESC LIMIT 200", (after,)).fetchall()))
            last = db.execute("SELECT COALESCE(MAX(n),0) FROM audit").fetchone()[0]
            jobs = [dict(r) for r in db.execute("SELECT id,url,state,reason,archive,attempts FROM jobs ORDER BY due")]
        if changes:
            comments, archived = {}, {}
            try:
                comments = {r['id']: r for r in decode_export(self.remark.export())[1:]}
            except Exception:
                pass  # An unavailable comment store must not suppress the digest.
            removed = {r['id'] for r in changes if r['action'] == 'removed'}
            for row in [r for r in jobs if r['id'] in removed and r['state'] == 'removed'][:5]:
                if row['archive']:
                    try:
                        with self.storage.download(row['archive']) as tar:
                            comment = json.load(tar.extractfile('comment.json'))
                            if comment['id'] == row['id']: archived[row['id']] = comment
                    except Exception:
                        pass  # Keep the decision and link even if S3 is unavailable.
            health = {task: time.time() - float(self.db.setting('last_' + task) or 0) < age
                      for task, age in [('scan', 7200), ('backup', 93600), ('history_cleanup', 7200)]}
            message = build_digest(now, self.config.get('mode', 'report'), changes, jobs, comments, archived, health, self.config)
            if message: self.storage.email(message[0], message[1], html=message[2])
        self.db.setting("digest_cursor", last)
        self.db.setting("digest_day", now.date().isoformat())

    def tick(self):
        # Independent jobs: a backup outage must not stop queued reviews, and a
        # broken sweep must not suppress failure notifications or monitoring.
        now = time.time()
        disk = self.storage_status()
        if self.db.setting("disk_level") != disk["level"]:
            self.db.audit(None, "storage", json.dumps(disk))
            self.db.setting("disk_level", disk["level"])
        if not self.paused():
            for name, interval, action in (("scan", 3600, self.scan),
                                            ("backup", 86400, lambda: self.storage.backup(self.remark)),
                                            ("history_cleanup", 3600, self.db.prune_history)):
                if (now - float(self.db.setting("last_" + name) or 0) >= interval and
                        now - float(self.db.setting("attempt_" + name) or 0) >= 300):
                    self.db.setting("attempt_" + name, now)
                    try:
                        action(); self.db.setting("last_" + name, time.time())
                    except Exception as exc:
                        self.db.audit(None, "failure", name + ": " + type(exc).__name__)
            self.process_one()
        try: self.digest()
        except Exception: print("Digest delivery failed; audit retained", flush=True)
        if now - float(self.db.setting("last_heartbeat") or 0) >= 300:
            healthy = (not self.paused() and disk["level"] == "ok" and
                       now - float(self.db.setting("last_scan") or 0) < 7200 and
                       now - float(self.db.setting("last_backup") or 0) < 93600)
            self.storage.heartbeat(healthy)
            self.db.setting("last_heartbeat", now)


def webhook_handler(worker):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass  # no credentials or submitted bodies in logs

        def do_POST(self):
            try:
                if self.path != "/webhook": self.send_error(404); return
                supplied = self.headers.get("Authorization", "")
                if not hmac.compare_digest(supplied, "Bearer " + worker.config["webhook_secret"]):
                    self.send_error(403); return
                if worker.disk_pressure.exists(): self.send_error(503); return
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096 or self.headers.get("Transfer-Encoding"):
                    self.send_error(413); return
                self.connection.settimeout(5)
                payload = json.loads(self.rfile.read(size))
                if set(payload) != {"id", "url", "site"} or payload["site"] != worker.config["site"]:
                    self.send_error(400); return
                worker.validate(payload["id"], payload["url"])
                worker.db.enqueue(payload["id"], payload["url"])
                self.send_response(202); self.end_headers()
            except (ValueError, KeyError, TypeError): self.send_error(400)
            except Exception: self.send_error(503)
    return Handler


@contextlib.contextmanager
def operation_lock(database):
    import fcntl  # Linux deployment; unit tests use the worker directly.
    with open(str(database.path) + ".lock", "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def main():
    from operations import Storage, restore, recover
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["serve", "status", "scan", "review", "show", "history", "keep", "remove", "backup", "restore", "recover", "resume"])
    parser.add_argument("--id")
    parser.add_argument("--reason", default="Owner moderation")
    parser.add_argument("--archive")
    parser.add_argument("--confirm-site")
    parser.add_argument("--retry-failures", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--replace-existing", action="store_true")
    args = parser.parse_args()
    config = load_config()
    db = Database(config.get("database", "/state/moderation.sqlite"))
    storage = Storage(config, db)
    worker = Worker(config, db, Remark(config), ModerationAdapter(config, db), storage)
    if args.command == "serve":
        server = ThreadingHTTPServer(("0.0.0.0", 8090), webhook_handler(worker))
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        while True:
            try:
                with operation_lock(db):
                    worker.tick()
            except Exception as exc:
                db.audit(None, "failure", type(exc).__name__ + " during scheduled work")
                # A failing sweep/backup must not suppress operational email.
                try: worker.digest()
                except Exception: print("Digest delivery failed; audit retained", flush=True)
                time.sleep(55)
            time.sleep(5)
    else:
        with operation_lock(db):
            if args.command == "scan": worker.scan(args.retry_failures)
            elif args.command == "backup": print(storage.backup(worker.remark))
            elif args.command == "restore":
                if args.confirm_site != config["site"] or not args.archive:
                    parser.error("restore requires --archive and --confirm-site matching the configured site")
                restore(worker, args.archive)
            elif args.command == "recover":
                if args.confirm_site != config["site"] or not args.archive:
                    parser.error("recover requires --archive and --confirm-site matching the configured site")
                recover(worker, args.archive, args.replace_existing)
            elif args.command == "resume":
                if args.confirm_site != config["site"]: parser.error("resume requires --confirm-site")
                worker.maintenance.unlink(missing_ok=True)
                db.audit(None, "resume", "Owner reopened commenting")
            elif args.command in {"keep", "remove"}:
                with db.connect() as conn: row = conn.execute("SELECT * FROM jobs WHERE id=?", (args.id,)).fetchone()
                if row is None: parser.error("Unknown comment; run scan first")
                comment = worker.remark.get(args.id, row["url"])
                if args.command == "remove": worker.remove(comment, args.reason)
                else:
                    digest = fingerprint(comment)
                    worker.finish(args.id, digest, "keep", args.reason)
                    with db.connect() as conn:
                        conn.execute("UPDATE jobs SET approved_hash=? WHERE id=?", (digest, args.id)); conn.commit()
            elif args.command == "show":
                with db.connect() as conn: row = conn.execute("SELECT * FROM jobs WHERE id=?", (args.id,)).fetchone()
                if row is None: parser.error("Unknown comment; run scan first")
                if args.archive:
                    with storage.download(args.archive) as tar: comment = json.load(tar.extractfile("comment.json"))
                    if comment["id"] != args.id: parser.error("Archive belongs to another comment")
                else: comment = worker.remark.get(args.id, row["url"])
                # Show review content without exposing recorded IPs or account email.
                comment["user"] = {k: comment.get("user", {}).get(k) for k in ("id", "name")}
                print(json.dumps({"comment": comment, "moderation": dict(row)}, indent=2))
            elif args.command == "history":
                if not args.id: parser.error("history requires --id")
                with db.connect() as conn:
                    print(json.dumps([dict(r) for r in conn.execute(
                        "SELECT * FROM audit WHERE id=? ORDER BY n", (args.id,))], indent=2))
            elif args.command == "status":
                month = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
                with db.connect() as conn:
                    counts = dict(conn.execute("SELECT state,COUNT(*) FROM jobs GROUP BY state"))
                    spend = conn.execute("SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM spending WHERE month=?", (month,)).fetchone()[0]
                print(json.dumps({"mode": config.get("mode", "report"), "paused": worker.paused(),
                    "maintenance": worker.maintenance.exists(), "storage": worker.storage_status(),
                    "jobs": counts, "reserved_or_spent_usd": spend / 1_000_000,
                    "monthly_limit_usd": config.get("monthly_budget_usd", 1),
                    "last_scan": db.setting("last_scan"), "last_backup": db.setting("last_backup")}, indent=2))
            else:
                if not 1 <= args.limit <= 100: parser.error("limit must be between 1 and 100")
                with db.connect() as conn:
                    query = "SELECT id,url,state,reason,archive FROM jobs WHERE state IN ('review','report_spam','failed') ORDER BY due LIMIT ?"
                    print(json.dumps([dict(row) for row in conn.execute(query, (args.limit,))], indent=2))


if __name__ == "__main__":
    main()
