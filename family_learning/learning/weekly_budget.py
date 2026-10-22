"""Crash-safe weekly request reservations in integer nanodollars.

Reserve a conservative maximum BEFORE contacting the provider. Missing usage,
disconnects, crashes and ambiguous failures keep the reservation charged. Only
validated provider usage can reduce it. No prompts or API credentials stored.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import uuid
from zoneinfo import ZoneInfo

MODEL = 'gpt-6-luna'
WEEKLY_LIMIT = 5_000_000_000
# Standard short-context USD prices verified 2026-10-21: $0.10 / $0.50 per M.
INPUT_RATE = 100
OUTPUT_RATE = 500


class BudgetExceeded(ValueError):
    pass


def week_key(now):
    local = now.astimezone(ZoneInfo('America/New_York'))
    return (local.date() - timedelta(days=local.weekday())).isoformat()


class Ledger:
    def __init__(self, directory, *, clock=lambda: datetime.now(timezone.utc), limit=WEEKLY_LIMIT):
        if type(limit) is not int or not 0 < limit <= WEEKLY_LIMIT:
            raise ValueError('Budget must be at most five dollars')
        self.clock, self.limit = clock, limit
        root = Path(directory)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        stat = root.lstat()
        if root.is_symlink() or stat.st_uid != os.getuid() or stat.st_mode & 0o077:
            raise ValueError('Budget directory must be private and parent-owned')
        self.path = root / 'weekly-budget.sqlite3'
        if self.path.is_symlink():
            raise ValueError('Budget database cannot be a symlink')
        with self.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY, week TEXT NOT NULL, reserved INTEGER NOT NULL,
                charged INTEGER NOT NULL, state TEXT NOT NULL,
                input_tokens INTEGER, output_tokens INTEGER
            )''')
        os.chmod(self.path, 0o600)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def reserve(self, input_bound, output_bound):
        if any(type(n) is not int or n < 0 for n in (input_bound, output_bound)):
            raise ValueError('Invalid token bounds')
        if input_bound > 200_000 or not 1 <= output_bound <= 2048:
            raise ValueError('Only bounded short-context tutoring is allowed')
        maximum = input_bound * INPUT_RATE + output_bound * OUTPUT_RATE
        week = week_key(self.clock())
        with self.db() as db:
            if db.execute('SELECT 1 FROM requests WHERE state=? LIMIT 1', ('review-required',)).fetchone():
                raise ValueError('Provider usage exceeded its reservation; parent review required')
            latest = db.execute('SELECT MAX(week) FROM requests').fetchone()[0]
            if latest and week < latest:
                raise ValueError('Clock moved to an earlier week; parent review required')
            used = db.execute('SELECT COALESCE(SUM(charged),0) FROM requests WHERE week=?', (week,)).fetchone()[0]
            if used + maximum > self.limit:
                raise BudgetExceeded('Weekly tutoring allowance reached. Ask your parent; it resets Monday at midnight Eastern.')
            key = uuid.uuid4().hex
            db.execute('INSERT INTO requests(id,week,reserved,charged,state) VALUES(?,?,?,?,?)',
                       (key, week, maximum, maximum, 'reserved'))
            return key

    def reconcile(self, key, usage):
        if not isinstance(usage, dict):
            return False  # Keep worst-case charge.
        counts = (usage.get('prompt_tokens'), usage.get('completion_tokens'))
        if any(type(n) is not int or n < 0 for n in counts):
            return False
        charged = counts[0] * INPUT_RATE + counts[1] * OUTPUT_RATE
        with self.db() as db:
            row = db.execute('SELECT * FROM requests WHERE id=?', (key,)).fetchone()
            if row is None:
                raise ValueError('Unknown reservation')
            if row['state'] != 'reserved':
                return False  # A replay cannot refund twice.
            if charged > row['reserved']:
                # A violated bound must never silently refund or keep serving.
                db.execute('UPDATE requests SET state=?,charged=? WHERE id=?', ('review-required', charged, key))
                return False
            db.execute('UPDATE requests SET charged=?,state=?,input_tokens=?,output_tokens=? WHERE id=?',
                       (charged, 'settled', *counts, key))
            return True

    def status(self):
        week = week_key(self.clock())
        with self.db() as db:
            used = db.execute('SELECT COALESCE(SUM(charged),0) FROM requests WHERE week=?', (week,)).fetchone()[0]
            frozen = bool(db.execute('SELECT 1 FROM requests WHERE state=? LIMIT 1', ('review-required',)).fetchone())
        return {'week_start': week, 'limit_nanodollars': self.limit,
                'used_nanodollars': used, 'remaining_nanodollars': max(0, self.limit-used),
                'review_required': frozen}
