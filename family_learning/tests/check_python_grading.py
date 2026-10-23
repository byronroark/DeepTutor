import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from deeptutor.family_learning.local_lessons import Actor, Lessons
from deeptutor.family_learning.python_grading import PythonGrader
from deeptutor.family_learning.python_runner import Result


class GradingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = Lessons(self.temp.name)
        self.parent = Actor("parent", "parent")
        self.child = Actor("child", "learner")
        self.course = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "deeptutor/family_learning/starter_lessons.json"
            ).read_text()
        )[0]
        self.course["lessons"][0].update(
            kind="python",
            expected_output="7\n",
            requirements=["assignment"],
            starter_code="stars = 5\nprint(stars + 2)",
        )
        self.course["lessons"][0].pop("answer")
        self.course["lessons"][0].pop("choices")
        self.key = self.engine.publish(self.parent, self.course)
        self.engine.assign(self.parent, self.key, self.child.id)
        self.runner = Mock()
        self.runner.run.return_value = Result("finished", "7\n", 0)
        self.grader = PythonGrader(self.engine, self.runner, clock=lambda: 1000)

    def run_program(self, code="stars = 5\nprint(stars + 2)", request=None):
        return self.grader.run("child", self.key, "name-a-value", code, request or uuid.uuid4().hex)

    def test_correct_output_and_required_concept_unlock(self):
        result = self.run_program()
        self.assertEqual(result["state"], "passed")
        view = self.engine.view(self.child, self.key)
        self.assertTrue(view["lessons"][1]["unlocked"])
        self.assertNotIn("expected_output", view["lessons"][0])

    def test_interrupted_attempt_requires_explicit_new_run(self):
        request = uuid.uuid4().hex
        with self.engine.db() as db:
            db.execute(
                "INSERT INTO python_jobs VALUES(?,?,?,?,?,?,?,?)",
                (request, "child", self.key, "name-a-value", "fixture", 0, 0, "interrupted"),
            )
        with self.assertRaisesRegex(ValueError, "interrupted"):
            self.run_program(request=request)
        self.runner.run.assert_not_called()
        self.assertEqual(self.run_program()["state"], "passed")

    def test_correct_output_without_required_assignment_does_not_pass(self):
        self.assertEqual(self.run_program("print(7)")["state"], "retry")

    def test_wrong_output_error_and_syntax_get_feedback(self):
        for execution in [
            Result("finished", "6\n", 0),
            Result("error", "NameError", 1),
            Result("time_limit", "", None),
            Result("output_limit", "x" * 16384, None),
        ]:
            self.runner.run.return_value = execution
            self.assertEqual(self.run_program()["state"], "retry")
        self.runner.run.side_effect = ValueError("Check your indentation.")
        self.assertEqual(self.run_program()["execution"], "syntax_feedback")

    def test_replay_does_not_execute_twice_and_payload_cannot_change(self):
        request = uuid.uuid4().hex
        result = self.run_program(request=request)
        self.assertEqual(result, self.run_program(request=request))
        self.runner.run.assert_called_once()
        with self.assertRaises(ValueError):
            self.run_program("print(8)", request=request)

    def test_unassigned_locked_and_plain_answer_cannot_execute_or_grade(self):
        with self.assertRaises(ValueError):
            self.engine.respond(self.child, self.key, "name-a-value", "7", uuid.uuid4().hex)
        with self.assertRaises(PermissionError):
            self.grader.run("stranger", self.key, "name-a-value", "print(7)", uuid.uuid4().hex)
        with self.assertRaises(PermissionError):
            self.grader.run("child", self.key, "use-a-value", "print(7)", uuid.uuid4().hex)
        self.runner.run.assert_not_called()

    def test_revocation_during_run_discards_result(self):
        def execution(code):
            self.engine.assign(self.parent, self.key, "child", False)
            return Result("finished", "7\n", 0)

        self.runner.run.side_effect = execution
        with self.assertRaises(PermissionError):
            self.run_program()
        with self.engine.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM work").fetchone()[0], 0)

    def test_retake_during_execution_discards_old_result(self):
        def execution(code):
            self.engine.reset_progress(self.parent, self.key, "child", None, 0, uuid.uuid4().hex)
            return Result("finished", "7\n", 0)

        self.runner.run.side_effect = execution
        with self.assertRaises(PermissionError):
            self.run_program()
        self.assertEqual(self.engine.view(self.child, self.key)["lessons"][0]["state"], "new")

    def test_old_python_replay_never_completes_a_retake(self):
        request = uuid.uuid4().hex
        self.run_program(request=request)
        self.engine.reset_progress(self.parent, self.key, "child", None, 0, uuid.uuid4().hex)
        with self.assertRaisesRegex(ValueError, "earlier attempt"):
            self.run_program(request=request)
        self.assertEqual(self.engine.view(self.child, self.key)["lessons"][0]["state"], "new")
        self.assertEqual(self.run_program()["state"], "passed")
        self.assertEqual(self.runner.run.call_count, 2)

    def test_revoke_then_reassign_during_run_also_discards_result(self):
        def execution(code):
            self.engine.assign(self.parent, self.key, "child", False)
            self.engine.assign(self.parent, self.key, "child", True)
            return Result("finished", "7\n", 0)

        self.runner.run.side_effect = execution
        with self.assertRaises(PermissionError):
            self.run_program()

    def test_rate_limit_and_pending_job_fail_closed(self):
        self.runner.run.return_value = Result("finished", "wrong", 0)
        for _ in range(10):
            self.run_program()
        with self.assertRaises(ValueError):
            self.run_program()
        self.assertEqual(self.runner.run.call_count, 10)

    def test_runner_unavailable_never_advances_progress(self):
        self.runner.run.side_effect = RuntimeError("Offline")
        with self.assertRaises(RuntimeError):
            self.run_program()
        self.assertEqual(self.engine.view(self.child, self.key)["lessons"][0]["state"], "new")

    def test_program_draft_is_saved_without_execution(self):
        self.engine.save_draft(self.child, self.key, "name-a-value", "stars =")
        self.assertEqual(self.engine.view(self.child, self.key)["lessons"][0]["draft"], "stars =")
        self.runner.run.assert_not_called()

    def test_second_run_is_refused_while_first_is_active(self):
        def execution(code):
            with self.assertRaisesRegex(ValueError, "already running"):
                self.run_program()
            return Result("finished", "7\n", 0)

        self.runner.run.side_effect = execution
        self.assertEqual(self.run_program()["state"], "passed")
        self.runner.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
