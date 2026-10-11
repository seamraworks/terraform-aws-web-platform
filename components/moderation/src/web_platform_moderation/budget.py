"""SQLite reservations, compatible with the existing comments spending table."""
import datetime as dt
import contextlib
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path


class BudgetExhausted(Exception):
    pass


@dataclass(frozen=True)
class Pricing:
    input_usd_per_million: float
    output_usd_per_million: float

    def __post_init__(self):
        if any(isinstance(v, bool) or not math.isfinite(v) or v < 0 for v in
               (self.input_usd_per_million, self.output_usd_per_million)):
            raise ValueError("Supply nonnegative finite model prices")

    def microdollars(self, input_tokens, output_tokens):
        return math.ceil(input_tokens * self.input_usd_per_million +
                         output_tokens * self.output_usd_per_million)


class SQLiteLedger:
    def __init__(self, path, pricing: Pricing):
        self.path, self.pricing = Path(path), pricing
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS spending (n INTEGER PRIMARY KEY AUTOINCREMENT, "
                       "month TEXT NOT NULL, reserved INTEGER NOT NULL, actual INTEGER)")

    def connect(self):
        return _Connection(sqlite3.connect(self.path, timeout=30))

    def reserve(self, body: bytes, limit: float, max_output_tokens: int):
        if isinstance(limit, bool) or not math.isfinite(limit) or limit <= 0:
            raise ValueError("Monthly budget must be positive and finite")
        cost = self.pricing.microdollars(len(body) + 8192, max_output_tokens)
        month = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            spent = db.execute("SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM spending "
                               "WHERE month=?", (month,)).fetchone()[0]
            if spent + cost > int(limit * 1_000_000):
                raise BudgetExhausted()
            ticket = db.execute("INSERT INTO spending(month,reserved) VALUES(?,?)", (month, cost)).lastrowid
            db.commit()
            return ticket
        finally:
            db.close()  # Also rolls back a rejected concurrent reservation.

    def settle(self, ticket, usage):
        if not isinstance(usage, dict):
            return
        values = [usage.get("input_tokens"), usage.get("output_tokens")]
        if any(type(v) is not int or v < 0 for v in values):
            return  # Unknown usage keeps the reservation rather than refunding it.
        with self.connect() as db:
            db.execute("UPDATE spending SET actual=? WHERE n=?", (self.pricing.microdollars(*values), ticket))


class _Connection:
    """A SQLite transaction context that also closes the underlying connection."""
    def __init__(self, db): self.db = db
    def __getattr__(self, name): return getattr(self.db, name)
    def __enter__(self):
        self.db.__enter__()
        return self
    def __exit__(self, *args):
        try: return self.db.__exit__(*args)
        finally: self.db.close()
