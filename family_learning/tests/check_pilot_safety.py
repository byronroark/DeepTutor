from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from deeptutor.family_learning.firewall import LocalLearningFirewall
from deeptutor.family_learning.local_lessons import Lessons
from deeptutor.family_learning.python_grading import PythonGrader
from deeptutor.family_learning.recovery import recover


class FirewallTests(unittest.TestCase):
    def setUp(self):
        self.callback_allowed = False
        self.learner_host = False
        app = FastAPI()

        @app.api_route("/{path:path}", methods=["GET", "POST"])
        def route(path: str):
            return {"visited": path}

        @app.websocket("/ws")
        async def ws(socket: WebSocket):
            await socket.accept()
            await socket.send_json({"unrestricted": True})

        app.add_middleware(
            LocalLearningFirewall,
            enabled=lambda: True,
            auth_enabled=lambda: True,
            decode_token=lambda token: (
                SimpleNamespace(role="admin" if token == "parent" else "user")
                if token in {"parent", "child"}
                else None
            ),
            parent_callback=lambda: self.callback_allowed,
            learner_host=lambda: self.learner_host,
        )
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_learner_host_allows_parent_dashboard_but_blocks_learner_ai(self):
        self.learner_host = True
        self.callback_allowed = True
        for token in ["parent", "child"]:
            headers = {"Authorization": "Bearer " + token}
            for path in [
                "/api/settings",
                "/api/auth/openai-codex/callback",
                "/api/family-learning/authoring/models",
                "/api/family-learning/authoring/generate",
            ]:
                self.assertEqual(
                    self.client.get(path, headers=headers).status_code,
                    200 if token == "parent" else 403,
                    path,
                )
            self.assertEqual(
                self.client.get("/api/family-learning", headers=headers).status_code, 200
            )
        self.assertEqual(self.client.get("/api/auth/openai-codex/callback").status_code, 401)

    def test_public_and_alternate_routes_are_blocked(self):
        for path in [
            "/api/settings",
            "/files/outputs/private",
            "/docs",
            "/api/auth/register",
            "/api/knowledge-bases",
            "/api/auth/openai-codex/start",
            "/api/family-learning-evil",
            "/ws/alternate",
        ]:
            self.assertEqual(
                self.client.get(path, headers={"Authorization": "Bearer child"}).status_code,
                403,
                path,
            )
            self.assertEqual(self.client.get(path).status_code, 401, path)

    def test_login_lesson_and_parent_behavior(self):
        self.assertEqual(self.client.post("/api/auth/login").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/status").status_code, 200)
        self.assertEqual(
            self.client.get(
                "/api/family-learning", headers={"Authorization": "Bearer child"}
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                "/api/settings", headers={"Authorization": "Bearer parent"}
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                "/api/settings", headers={"Authorization": "Bearer forged"}
            ).status_code,
            401,
        )

    def test_learner_websocket_never_upgrades(self):
        from starlette.websockets import WebSocketDisconnect

        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/ws?token=child"):
                pass

    def test_only_explicit_parent_callback_get_can_reach_state_validator(self):
        path = "/api/auth/openai-codex/callback"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.callback_allowed = True
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.post(path).status_code, 401)
        self.assertEqual(self.client.get("/api/settings").status_code, 401)


class RecoveryTests(unittest.TestCase):
    def test_only_labelled_containers_removed_and_no_grades_awarded(self):
        with tempfile.TemporaryDirectory() as root:
            engine = Lessons(root)
            PythonGrader(engine, object())
            with engine.db() as db:
                db.execute(
                    "INSERT INTO python_jobs VALUES(?,?,?,?,?,?,?,?)",
                    ("job", "child", "course", "lesson", "fingerprint", 0, 0, "running"),
                )
            results = [
                SimpleNamespace(stdout="a" * 12 + "\n"),
                SimpleNamespace(stdout=""),
                SimpleNamespace(stdout=""),
            ]
            with patch(
                "deeptutor.family_learning.recovery.subprocess.run", side_effect=results
            ) as command:
                recover(engine, "docker")
            self.assertEqual(command.call_args_list[1].args[0], ["docker", "rm", "-f", "a" * 12])
            with engine.db() as db:
                self.assertEqual(
                    db.execute("SELECT state FROM python_jobs").fetchone()[0], "interrupted"
                )
                self.assertEqual(db.execute("SELECT count(*) FROM work").fetchone()[0], 0)

    def test_cleanup_failure_never_releases_pending_jobs(self):
        with tempfile.TemporaryDirectory() as root:
            engine = Lessons(root)
            with patch(
                "deeptutor.family_learning.recovery.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "docker"),
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    recover(engine, "docker")


if __name__ == "__main__":
    unittest.main()
