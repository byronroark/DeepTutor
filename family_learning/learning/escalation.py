"""Durable notification escalation; never authorizes or executes an action.

Callers must validate requests with their existing scoped backend before ingest.
Only a backend-confirmed terminal result may settle a request. Discord delivery
is an outbox notification, not approval. No network listeners or secrets here.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

KINDS = frozenset({'learning', 'software', 'break'})
# Queued/running already mean the parent responded; stop escalation even while
# an approved installation is still being executed by its existing worker.
TERMINAL = frozenset({'approved', 'denied', 'expired', 'withdrawn', 'queued', 'running', 'completed', 'failed'})
SLUG = re.compile(r'[a-z][a-z0-9-]{0,63}')
IDENTIFIER = re.compile(r'[a-f0-9]{32}')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


class Queue:
    def __init__(self, directory, *, clock=time.time):
        self.clock = clock
        root = Path(directory)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        st = root.lstat()
        if root.is_symlink() or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise ValueError('Escalation directory must be private and owned by this account')
        self.path = root / 'escalation.sqlite3'
        if self.path.is_symlink():
            raise ValueError('Escalation database cannot be a symlink')
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, kind TEXT NOT NULL,
                    backend_id TEXT NOT NULL, parent TEXT NOT NULL,
                    snapshot TEXT NOT NULL, digest TEXT NOT NULL,
                    first_seen REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    lease TEXT, lease_until REAL, delivered TEXT,
                    UNIQUE(source, kind, backend_id, parent)
                );
                CREATE TABLE IF NOT EXISTS heartbeats (
                    parent TEXT PRIMARY KEY, seen REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY, request_id TEXT, time REAL NOT NULL,
                    event TEXT NOT NULL, detail TEXT NOT NULL
                );
            ''')
        os.chmod(self.path, 0o600)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self, db, request_id, event, detail=''):
        db.execute('INSERT INTO events(request_id,time,event,detail) VALUES(?,?,?,?)',
                   (request_id, self.clock(), event, detail))

    def observe(self, source, kind, backend_id, parent, snapshot):
        """Called after a backend validates a currently pending request.

        The first receipt starts the three-minute desktop response window.
        Repeated polling and service restarts never reset it.
        """
        if not SLUG.fullmatch(source) or not SLUG.fullmatch(parent):
            raise ValueError('Invalid enrolled source or parent')
        if kind not in KINDS or not IDENTIFIER.fullmatch(backend_id):
            raise ValueError('Invalid request kind or ID')
        if not isinstance(snapshot, dict):
            raise ValueError('Expected a validated request object')
        raw = json.dumps(snapshot, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if len(raw.encode()) > 65536:
            raise ValueError('Oversized request')
        fingerprint = digest(snapshot)
        with self.transaction() as db:
            old = db.execute('SELECT * FROM requests WHERE source=? AND kind=? AND backend_id=? AND parent=?',
                             (source, kind, backend_id, parent)).fetchone()
            if old:
                if old['digest'] != fingerprint:
                    raise ValueError('Request changed; a fresh backend request is required')
                return old['id']
            key = uuid.uuid4().hex
            db.execute('INSERT INTO requests(id,source,kind,backend_id,parent,snapshot,digest,first_seen) VALUES(?,?,?,?,?,?,?,?)',
                       (key, source, kind, backend_id, parent, raw, fingerprint, self.clock()))
            self.event(db, key, 'desktop-first')
            return key

    def heartbeat(self, parent):
        """Only an authenticated desktop-helper heartbeat may call this."""
        if not SLUG.fullmatch(parent):
            raise ValueError('Invalid enrolled parent')
        with self.transaction() as db:
            db.execute('INSERT INTO heartbeats(parent,seen) VALUES(?,?) ON CONFLICT(parent) DO UPDATE SET seen=excluded.seen',
                       (parent, self.clock()))

    def claim(self):
        """Lease one due Discord escalation; restart-safe, one active sender.

        A previously observed desktop is unreachable after 60 seconds without
        its authenticated heartbeat. Unknown availability waits three minutes.
        Recheck the backend immediately before sending; settle stale requests.
        """
        now = self.clock()
        with self.transaction() as db:
            row = db.execute('''SELECT r.* FROM requests r LEFT JOIN heartbeats h ON r.parent=h.parent
                WHERE r.status='pending' AND r.delivered IS NULL
                AND (r.lease_until IS NULL OR r.lease_until<=?)
                AND (r.first_seen+180<=? OR (h.seen IS NOT NULL AND h.seen+60<=?))
                ORDER BY r.first_seen,r.id LIMIT 1''', (now, now, now)).fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            db.execute('UPDATE requests SET lease=?,lease_until=? WHERE id=?',
                       (token, now + 30, row['id']))
            self.event(db, row['id'], 'discord-leased')
            return {**dict(row), 'lease': token, 'snapshot': json.loads(row['snapshot'])}

    def sent(self, request_id, lease, message_id):
        if not isinstance(message_id, str) or not re.fullmatch(r'[0-9]{17,22}', message_id):
            raise ValueError('Invalid Discord message ID')
        with self.transaction() as db:
            cursor = db.execute('UPDATE requests SET delivered=?,lease=NULL,lease_until=NULL '
                                'WHERE id=? AND lease=? AND lease_until>? AND status=?',
                                (message_id, request_id, lease, self.clock(), 'pending'))
            if cursor.rowcount != 1:
                raise ValueError('Escalation was settled or its delivery lease expired')
            self.event(db, request_id, 'discord-sent', message_id)

    def settle(self, source, kind, backend_id, status):
        """Apply only a status freshly confirmed by the authoritative backend.

        Settle ALL parent channels together. A Discord button alone must never
        call this; it first needs the normal scoped approval service to accept.
        """
        if status not in TERMINAL:
            raise ValueError('Expected a confirmed terminal result')
        with self.transaction() as db:
            rows = db.execute('SELECT id FROM requests WHERE source=? AND kind=? AND backend_id=? AND status=?',
                              (source, kind, backend_id, 'pending')).fetchall()
            db.execute('UPDATE requests SET status=?,lease=NULL,lease_until=NULL WHERE source=? AND kind=? AND backend_id=? AND status=?',
                       (status, source, kind, backend_id, 'pending'))
            for row in rows:
                self.event(db, row['id'], 'backend-settled', status)
