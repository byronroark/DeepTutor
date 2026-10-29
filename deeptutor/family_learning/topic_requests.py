"""Local learning ideas; approval never invokes AI or changes assignments."""

from contextlib import contextmanager
import os
from pathlib import Path
import re
import sqlite3
import time


def topic(value):
    if (
        not isinstance(value, str)
        or not 3 <= len(value.strip()) <= 160
        or not all(c.isprintable() for c in value)
    ):
        raise ValueError("Use a short topic of 3–160 characters")
    return value.strip()


class Topics:
    def __init__(self, root):
        root = Path(root)
        if root.is_symlink() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
            raise ValueError("Private local topic storage required")
        self.path = root / "topic-requests.sqlite3"
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd)
        os.close(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Private topic database required")
        with self.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS topics(id TEXT PRIMARY KEY,learner TEXT,topic TEXT,created REAL,status TEXT,approved_topic TEXT,parent TEXT)"
            )

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def ask(self, actor, identifier, value):
        if actor.role != "learner":
            raise PermissionError("Learner account required")
        value = topic(value)
        if not isinstance(identifier, str) or not re.fullmatch("[a-f0-9]{32}", identifier):
            raise ValueError("Invalid request ID")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM topics WHERE id=?", (identifier,)).fetchone()
            if old:
                if old["learner"] != actor.id or old["topic"] != value:
                    raise ValueError("Request ID already used")
                return dict(old)
            rows = db.execute(
                "SELECT created FROM topics WHERE learner=? AND status='pending'", (actor.id,)
            ).fetchall()
            if len(rows) >= 3 or any(time.time() - r["created"] < 60 for r in rows):
                raise ValueError("Wait for a parent to review your recent topic requests")
            db.execute(
                "INSERT INTO topics VALUES(?,?,?,?,'pending','','')",
                (identifier, actor.id, value, time.time()),
            )
            return dict(db.execute("SELECT * FROM topics WHERE id=?", (identifier,)).fetchone())

    def list(self, actor, pending=False):
        with self.db() as db:
            if actor.role == "parent":
                rows = db.execute("SELECT * FROM topics ORDER BY created DESC LIMIT 100").fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM topics WHERE learner=? ORDER BY created DESC LIMIT 30",
                    (actor.id,),
                ).fetchall()
            return [dict(row) for row in rows if not pending or row["status"] == "pending"]

    def decide(self, actor, identifier, choice, expected, replacement=None):
        if actor.role != "parent":
            raise PermissionError("Parent account required")
        if choice not in ["approve", "deny"]:
            raise ValueError("Invalid topic decision")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM topics WHERE id=?", (identifier,)).fetchone()
            if not row or row["status"] != "pending" or row["topic"] != expected:
                raise ValueError("Topic request changed or was already reviewed")
            approved = (
                topic(replacement if replacement is not None else row["topic"])
                if choice == "approve"
                else ""
            )
            db.execute(
                "UPDATE topics SET status=?,approved_topic=?,parent=? WHERE id=?",
                ("approved" if choice == "approve" else "denied", approved, actor.id, identifier),
            )
            return dict(db.execute("SELECT * FROM topics WHERE id=?", (identifier,)).fetchone())
