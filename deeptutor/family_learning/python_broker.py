"""Narrow host-side Unix-socket service; only this process talks to Docker."""

import argparse
import hmac
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import secrets
import socket
import socketserver
import stat
import threading

from .broker_credentials import read_token
from .local_lessons import Lessons
from .python_grading import PythonGrader
from .python_runner import PythonRunner


class Broker(
    socketserver.ThreadingMixIn, getattr(socketserver, "UnixStreamServer", socketserver.TCPServer)
):
    daemon_threads = True
    request_queue_size = 4

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(4)
        super().__init__(*args, **kwargs)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(10)
        return request, address

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        try:
            self.connection.settimeout(10)
            if self.path != "/run" or not hmac.compare_digest(
                self.headers.get("Authorization", "").encode("utf-8"),
                ("Bearer " + self.server.token).encode("ascii"),
            ):
                return self.reply(403, {"detail": "Broker request refused"})
            if (
                self.headers.get("Transfer-Encoding")
                or self.headers.get("Content-Type") != "application/json"
            ):
                raise ValueError("Use bounded JSON requests")
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 131072:
                raise ValueError("Invalid request length")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("Incomplete request")
            data = json.loads(raw)
            if not isinstance(data, dict) or set(data) != {
                "learner",
                "course",
                "lesson",
                "code",
                "request_id",
            }:
                raise ValueError("Unsupported broker request")
            if any(not isinstance(value, str) for value in data.values()):
                raise ValueError("Broker fields must be text")
            result = self.server.grader.run(**data)
            self.reply(200, result)
        except PermissionError:
            self.reply(403, {"detail": "Assignment unavailable or changed during execution"})
        except ValueError as error:
            self.reply(409, {"detail": str(error)})
        except (RuntimeError, OSError):
            self.reply(503, {"detail": "Python runner unavailable; ask your parent"})


def serve(socket_path, token_path, lesson_directory):
    if os.name != "posix":
        raise RuntimeError("The isolated Python broker requires a Unix host")
    os.umask(0o077)
    path = Path(socket_path)
    parent = path.parent
    if parent.is_symlink():
        raise ValueError("Broker directory cannot be a link")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.stat().st_uid != os.getuid() or parent.stat().st_mode & 0o077:
        raise ValueError("Broker directory must be private and owned")
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("Refusing an unexpected socket path")
        probe = socket.socket(socket.AF_UNIX)
        try:
            probe.connect(str(path))
        except ConnectionRefusedError:
            path.unlink()
        else:
            raise ValueError("A broker is already listening")
        finally:
            probe.close()
    grader = PythonGrader(Lessons(lesson_directory), PythonRunner())
    token = read_token(token_path)
    with Broker(str(path), Handler) as server:
        path.chmod(0o600)
        server.grader, server.token = grader, token
        try:
            server.serve_forever()
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--lessons", required=True)
    parser.add_argument("--initialize-token", action="store_true")
    args = parser.parse_args()
    if args.initialize_token:
        # Explicit, exclusive creation; never silently rotate an enrolled key.
        descriptor = os.open(
            args.token, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "w") as target:
            target.write(secrets.token_urlsafe(48))
    serve(args.socket, args.token, args.lessons)
