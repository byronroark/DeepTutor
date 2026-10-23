"""Single-broker startup recovery; never reruns or awards interrupted work."""

from contextlib import contextmanager
import os
from pathlib import Path
import re
import subprocess


@contextmanager
def broker_lock():
    import fcntl

    root = Path.home() / ".local/state/family-learning-runner"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise RuntimeError("Runner state must be private and owned")
    fd = os.open(root / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def recover(engine, docker):
    def remaining():
        result = subprocess.run(
            [docker, "ps", "-aq", "--filter", "label=org.family-learning.runner=1"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        ids = result.stdout.split()
        if any(not re.fullmatch(r"[a-f0-9]{12,64}", key) for key in ids):
            raise RuntimeError("Unexpected runner container identity")
        return ids

    for container in remaining():
        subprocess.run([docker, "rm", "-f", container], capture_output=True, timeout=15, check=True)
    if remaining():
        raise RuntimeError("Runner cleanup could not be verified")
    with engine.db() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='python_jobs'"
        ).fetchone()
        if exists:
            db.execute("UPDATE python_jobs SET state='interrupted' WHERE state='running'")
