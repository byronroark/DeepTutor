"""Backend client for the narrowly scoped host broker, never for Docker."""

import http.client
import json
import socket

from .broker_credentials import read_token


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=30)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def check_solution(socket_path, token_path, actor, lesson, code):
    if actor.role != "parent":
        raise PermissionError("Only a parent may check reference programs")
    connection = UnixConnection(socket_path)
    try:
        connection.request(
            "POST",
            "/check-reference",
            json.dumps({"lesson": lesson, "code": code}).encode(),
            {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + read_token(token_path),
            },
        )
        response = connection.getresponse()
        raw = response.read(131073)
        if len(raw) > 131072:
            raise RuntimeError("Oversized check response")
        data = json.loads(raw)
        if response.status == 409:
            raise ValueError(str(data.get("detail", "Reference program needs review")))
        if response.status != 200 or data != {"checked": True}:
            raise RuntimeError("Reference sandbox is unavailable")
        return data
    finally:
        connection.close()


def run_python(socket_path, token_path, actor, course, lesson, code, request_id):
    if actor.role != "learner":
        raise PermissionError("Only an assigned learner can run an exercise")
    connection = UnixConnection(socket_path)
    try:
        connection.request(
            "POST",
            "/run",
            json.dumps(
                {
                    "learner": actor.id,
                    "course": course,
                    "lesson": lesson,
                    "code": code,
                    "request_id": request_id,
                }
            ).encode(),
            {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + read_token(token_path),
            },
        )
        response = connection.getresponse()
        raw = response.read(131073)
        if len(raw) > 131072:
            raise RuntimeError("Oversized broker response")
        data = json.loads(raw)
        if response.status == 403:
            raise PermissionError("Python assignment unavailable")
        if response.status == 409:
            raise ValueError(str(data.get("detail", "Exercise request needs review")))
        if response.status != 200:
            raise RuntimeError("Python runner is not ready")
        return data
    finally:
        connection.close()
