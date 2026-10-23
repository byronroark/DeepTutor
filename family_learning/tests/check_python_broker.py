from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from deeptutor.family_learning.local_lessons import Actor
from deeptutor.family_learning.python_broker import Broker, Handler
from deeptutor.family_learning.python_client import UnixConnection, check_solution, run_python


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "broker.sock")
        self.token = Path(self.temp.name) / "token"
        self.token.write_text("a" * 48)
        self.token.chmod(0o600)
        self.server = Broker(self.path, Handler)
        self.server.token = "a" * 48
        self.server.grader = Mock()
        self.server.grader.run.return_value = {
            "state": "retry",
            "feedback": "Try again",
            "output": "6\n",
            "execution": "finished",
        }
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def call(self, role="learner"):
        return run_python(
            self.path, self.token, Actor("child", role), "course", "exercise", "print(6)", "a" * 32
        )

    def test_narrow_request_uses_authenticated_backend_actor(self):
        self.assertEqual(self.call()["state"], "retry")
        self.server.grader.run.assert_called_once_with(
            learner="child",
            course="course",
            lesson="exercise",
            code="print(6)",
            request_id="a" * 32,
        )

    def test_bad_token_cannot_reach_grader(self):
        self.token.write_text("b" * 48)
        with self.assertRaises(PermissionError):
            self.call()
        self.server.grader.run.assert_not_called()

    def test_parent_cannot_pose_as_assigned_learner(self):
        with self.assertRaises(PermissionError):
            self.call("parent")
        self.server.grader.run.assert_not_called()

    def test_reference_check_uses_sandbox_and_does_not_create_learner_progress(self):
        lesson = {
            "id": "test",
            "title": "Test",
            "kind": "python",
            "explanation": "Count",
            "question": "Print six",
            "hints": [],
            "success": "Yes",
            "expected_output": "6\n",
        }
        self.server.grader.runner.run.return_value = SimpleNamespace(state="finished", output="6\n")
        self.assertEqual(
            check_solution(self.path, self.token, Actor("parent", "parent"), lesson, "print(6)"),
            {"checked": True},
        )
        self.server.grader.runner.run.assert_called_once_with("print(6)")
        self.server.grader.run.assert_not_called()
        with self.assertRaises(PermissionError):
            check_solution(self.path, self.token, Actor("learner", "learner"), lesson, "print(6)")

    def test_reference_check_refuses_bad_token_and_unsafe_programs(self):
        lesson = {
            "id": "test",
            "title": "Test",
            "kind": "python",
            "explanation": "Count",
            "question": "Print six",
            "hints": [],
            "success": "Yes",
            "expected_output": "6\n",
        }
        with self.assertRaises(ValueError):
            check_solution(self.path, self.token, Actor("parent", "parent"), lesson, "import os")
        self.token.write_text("b" * 48)
        with self.assertRaises(RuntimeError):
            check_solution(self.path, self.token, Actor("parent", "parent"), lesson, "print(6)")
        self.server.grader.runner.run.assert_not_called()

    def test_arbitrary_command_fields_refused(self):
        connection = UnixConnection(self.path)
        try:
            connection.request(
                "POST",
                "/run",
                b'{"command":"sudo anything"}',
                {"Content-Type": "application/json", "Authorization": "Bearer " + "a" * 48},
            )
            self.assertEqual(connection.getresponse().status, 409)
        finally:
            connection.close()
        self.server.grader.run.assert_not_called()

    def test_revoked_and_unavailable_results_propagate_safely(self):
        self.server.grader.run.side_effect = PermissionError("Revoked")
        with self.assertRaises(PermissionError):
            self.call()
        self.server.grader.run.side_effect = RuntimeError("Host-private diagnostic")
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            self.call()


if __name__ == "__main__":
    unittest.main()
