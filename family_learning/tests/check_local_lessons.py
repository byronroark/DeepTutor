import concurrent.futures
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deeptutor/family_learning"))
from local_lessons import Actor, Lessons

ROOT = Path(__file__).resolve().parents[1]


class LessonsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = Lessons(self.temp.name)
        self.parent = Actor("parent-a", "parent")
        self.child = Actor("learner-a", "learner")
        self.samples = json.loads(
            (ROOT.parent / "deeptutor/family_learning/starter_lessons.json").read_text()
        )
        self.course = self.engine.publish(self.parent, self.samples[0])
        self.engine.assign(self.parent, self.course, self.child.id)

    def answer(self, lesson, value, request=None):
        return self.engine.respond(
            self.child, self.course, lesson, value, request or uuid.uuid4().hex
        )

    def test_retry_feedback_unlock_and_restart(self):
        with self.assertRaises(PermissionError):
            self.answer("use-a-value", "7")
        self.assertEqual(self.answer("name-a-value", "1")["state"], "retry")
        self.assertEqual(self.answer("name-a-value", "0")["state"], "passed")
        self.assertTrue(self.engine.view(self.child, self.course)["lessons"][1]["unlocked"])
        self.assertEqual(self.answer("use-a-value", "7.0")["state"], "passed")
        restarted = Lessons(self.temp.name)
        self.assertEqual(restarted.view(self.child, self.course)["lessons"][1]["state"], "passed")

    def test_lesson_retake_archives_results_and_preserves_later_work(self):
        self.answer("name-a-value", "1")
        old = uuid.uuid4().hex
        self.answer("name-a-value", "0", old)
        self.answer("use-a-value", "7")
        request = uuid.uuid4().hex
        result = self.engine.reset_progress(
            self.parent, self.course, self.child.id, "name-a-value", 0, request
        )
        self.assertEqual(
            result,
            self.engine.reset_progress(
                self.parent, self.course, self.child.id, "name-a-value", 0, request
            ),
        )
        view = self.engine.view(self.child, self.course)
        self.assertEqual(view["lessons"][0]["state"], "new")
        self.assertFalse(view["lessons"][1]["unlocked"])
        previous = view["history"][0]["results"][0]
        self.assertEqual((previous["state"], previous["attempts"]), ("passed", 2))
        self.assertNotIn("draft", previous)
        with self.assertRaisesRegex(ValueError, "earlier attempt"):
            self.answer("name-a-value", "0", old)
        self.answer("name-a-value", "0")
        view = Lessons(self.temp.name).view(self.child, self.course)
        self.assertEqual(view["lessons"][0]["attempts"], 1)
        self.assertEqual(view["lessons"][1]["state"], "passed")
        self.assertEqual(len(view["history"]), 1)

    def test_course_retake_and_other_learners_history_is_private(self):
        self.answer("name-a-value", "0")
        self.answer("use-a-value", "7")
        other = Actor("learner-b", "learner")
        self.engine.assign(self.parent, self.course, other.id)
        self.engine.respond(other, self.course, "name-a-value", "0", uuid.uuid4().hex)
        self.engine.reset_progress(
            self.parent, self.course, self.child.id, None, 0, uuid.uuid4().hex
        )
        self.assertEqual(len(self.engine.view(self.child, self.course)["history"][0]["results"]), 2)
        self.assertEqual(self.engine.view(other, self.course)["history"], [])
        self.assertEqual(self.engine.view(other, self.course)["lessons"][0]["state"], "passed")

    def test_retake_rejects_wrong_owner_learner_stale_version_and_empty_progress(self):
        self.answer("name-a-value", "0")
        for actor in [self.child, Actor("other-parent", "parent")]:
            with self.assertRaises(PermissionError):
                self.engine.reset_progress(
                    actor, self.course, self.child.id, None, 0, uuid.uuid4().hex
                )
        self.engine.reset_progress(
            self.parent, self.course, self.child.id, None, 0, uuid.uuid4().hex
        )
        self.answer("name-a-value", "0")
        with self.assertRaisesRegex(ValueError, "Refresh"):
            self.engine.reset_progress(
                self.parent, self.course, self.child.id, None, 0, uuid.uuid4().hex
            )
        self.assertEqual(self.engine.view(self.child, self.course)["lessons"][0]["state"], "passed")

    def test_old_pending_writing_cannot_grade_new_attempt(self):
        self.course = self.engine.publish(self.parent, self.samples[2])
        self.engine.assign(self.parent, self.course, self.child.id)
        result = self.answer("book-report", "My original writing")
        self.engine.reset_progress(
            self.parent, self.course, self.child.id, "book-report", 0, uuid.uuid4().hex
        )
        with self.assertRaises(ValueError):
            self.engine.review(self.parent, result["submission"], True, "Old approval")
        self.assertEqual(self.engine.view(self.child, self.course)["lessons"][0]["state"], "new")
        self.assertEqual(
            self.engine.submissions(self.parent, self.course)[0]["writing"], "My original writing"
        )
        self.assertEqual(
            self.engine.submissions(self.parent, self.course)[0]["decision"], "archived"
        )

    def test_answer_keys_and_future_material_not_exposed(self):
        view = self.engine.view(self.child, self.course)
        self.assertNotIn("answer", view["lessons"][0])
        self.assertNotIn("hints", view["lessons"][0])
        self.assertNotIn("question", view["lessons"][1])

    def test_assignment_checked_on_every_call_even_replay(self):
        request = uuid.uuid4().hex
        self.answer("name-a-value", "1", request)
        self.engine.assign(self.parent, self.course, self.child.id, active=False)
        with self.assertRaises(PermissionError):
            self.answer("name-a-value", "1", request)
        with self.assertRaises(PermissionError):
            self.engine.view(self.child, self.course)

    def test_parent_and_learner_boundaries(self):
        with self.assertRaises(PermissionError):
            self.engine.publish(self.child, self.samples[0])
        with self.assertRaises(PermissionError):
            self.engine.assign(Actor("other-parent", "parent"), self.course, "learner-b")
        with self.assertRaises(PermissionError):
            self.engine.view(Actor("learner-b", "learner"), self.course)
        with self.assertRaises(PermissionError):
            self.engine.submissions(self.child, self.course)

    def test_retries_are_idempotent_and_payload_bound(self):
        request = uuid.uuid4().hex
        first = self.answer("name-a-value", "1", request)
        self.assertEqual(first, self.answer("name-a-value", "1", request))
        self.assertEqual(self.engine.view(self.child, self.course)["lessons"][0]["attempts"], 1)
        with self.assertRaises(ValueError):
            self.answer("name-a-value", "2", request)

    def test_concurrent_replay_does_not_count_twice(self):
        request = uuid.uuid4().hex
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.answer("name-a-value", "1", request), range(4)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(self.engine.view(self.child, self.course)["lessons"][0]["attempts"], 1)

    def test_published_revision_is_immutable(self):
        changed = copy.deepcopy(self.samples[0])
        changed["title"] = "A revised lesson"
        revision = self.engine.publish(self.parent, changed)
        self.assertNotEqual(revision, self.course)
        with self.assertRaises(PermissionError):
            self.engine.view(self.child, revision)
        self.assertEqual(
            self.engine.view(self.child, self.course)["title"], self.samples[0]["title"]
        )

    def test_writing_draft_review_revision_and_approval(self):
        self.course = self.engine.publish(self.parent, self.samples[2])
        self.engine.assign(self.parent, self.course, self.child.id)
        self.engine.save_draft(self.child, self.course, "book-report", "My draft")
        self.assertEqual(
            self.engine.view(self.child, self.course)["lessons"][0]["draft"], "My draft"
        )
        result = self.answer("book-report", "My first report")
        self.assertEqual(result["state"], "review")
        with self.assertRaises(ValueError):
            self.engine.save_draft(self.child, self.course, "book-report", "changed while pending")
        with self.assertRaises(PermissionError):
            self.engine.review(self.child, result["submission"], True, "approve myself")
        self.engine.review(
            self.parent, result["submission"], False, "Add an example from the book."
        )
        self.assertEqual(self.engine.view(self.child, self.course)["lessons"][0]["state"], "revise")
        revised = self.answer("book-report", "A report with an example")
        self.engine.review(
            self.parent, revised["submission"], True, "Your example supports your opinion clearly."
        )
        self.assertEqual(self.engine.view(self.child, self.course)["lessons"][0]["state"], "passed")
        originals = self.engine.submissions(self.parent, self.course)
        self.assertEqual(len(originals), 2)
        self.assertIn("My first report", [item["writing"] for item in originals])
        with self.assertRaises(ValueError):
            self.engine.review(self.parent, revised["submission"], False, "second decision")

    def test_python_execution_and_invalid_numbers_fail_closed(self):
        changed = copy.deepcopy(self.samples[0])
        changed["lessons"][0]["kind"] = "python"
        with self.assertRaises(ValueError):
            self.engine.publish(self.parent, changed)
        self.answer("name-a-value", "0")
        for value in ["NaN", "Infinity", '__import__("os").system("id")']:
            self.assertEqual(self.answer("use-a-value", value)["state"], "retry")


if __name__ == "__main__":
    unittest.main()
