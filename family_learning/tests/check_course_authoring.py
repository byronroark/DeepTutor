"""Private generation, review/version checks, and isolated reference validation."""

import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.family_learning.course_authoring import Authoring, validate_bundle
from deeptutor.family_learning.http_api import create_router
from deeptutor.family_learning.local_lessons import Actor, Lessons
from deeptutor.family_learning.solution_check import check_reference

BUNDLE = {
    "document": {
        "format": "family-learning-course",
        "version": 1,
        "course": {
            "title": "Stars",
            "subject": "Python",
            "objectives": ["Use a variable"],
            "lessons": [
                {
                    "id": "stars",
                    "title": "Count stars",
                    "kind": "python",
                    "explanation": "A variable stores a value.",
                    "question": "Store 5, then print 7 by adding 2.",
                    "hints": ["Use print."],
                    "success": "Well done!",
                    "starter_code": "stars = 5",
                    "expected_output": "7\n",
                    "requirements": ["assignment"],
                }
            ],
        },
    },
    "solutions": {"stars": "stars = 5\nprint(stars + 2)"},
}


class AuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = Lessons(self.temp.name)
        self.parent = Actor("parent", "parent")
        self.store = Authoring(self.engine)
        self.role = "admin"
        self.user = "parent"
        self.generator = AsyncMock(return_value=json.dumps(BUNDLE))
        self.checker = Mock(return_value={"checked": True})

        async def auth():
            return SimpleNamespace(user_id=self.user, role=self.role)

        app = FastAPI()
        app.include_router(
            create_router(
                auth,
                lambda: self.engine,
                lambda: True,
                lambda: "http://testserver",
                lambda: [],
                course_generator=self.generator,
                generation_models=lambda _: {"models": [{"model": "test-model", "name": "Test"}]},
                course_checker=self.checker,
            ),
            prefix="/api/family-learning",
        )
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.base = "/api/family-learning/authoring"
        self.headers = {"Origin": "http://testserver"}
        self.brief = {
            "request_id": uuid.uuid4().hex,
            "topic": "Stars",
            "level": "Beginner age 9",
            "goals": "Use variables",
            "exercises": 1,
            "minutes": 15,
            "kinds": ["python"],
            "instructions": "Friendly examples",
            "model": "test-model",
        }

    def post(self, path, body, headers=None):
        return self.client.post(
            self.base + path, json=body, headers=self.headers if headers is None else headers
        )

    def generate(self):
        response = self.post("/generate", self.brief)
        self.assertEqual(response.status_code, 202, response.text)
        return self.brief["request_id"]

    def test_generated_draft_is_private_persistent_and_never_assigned(self):
        key = self.generate()
        draft = self.store.read(self.parent, key)
        self.assertEqual(draft["status"], "ready")
        self.assertEqual(draft["bundle"], BUNDLE)
        self.assertEqual(self.engine.catalog(self.parent), [])
        with self.engine.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM assignments").fetchone()[0], 0)
        self.assertEqual(
            Authoring(Lessons(self.temp.name)).read(self.parent, key)["bundle"], BUNDLE
        )
        self.assertEqual(
            set(self.generator.call_args.args[1]),
            set(self.brief) - {"request_id"} | {"source", "source_version"},
        )

    def test_learner_and_other_parent_cannot_access_generation_or_drafts(self):
        key = self.generate()
        self.role = "user"
        self.user = "learner"
        for path in ["/drafts", "/drafts/" + key, "/models"]:
            self.assertEqual(self.client.get(self.base + path).status_code, 403)
        self.assertEqual(self.post("/generate", self.brief).status_code, 403)
        self.assertEqual(
            self.post("/drafts/" + key + "/publish", {"version": 1, "reviewed": True}).status_code,
            403,
        )
        self.role = "admin"
        self.user = "other"
        self.assertEqual(self.client.get(self.base + "/drafts/" + key).status_code, 403)
        self.assertEqual(self.generator.await_count, 1)

    def test_cross_origin_and_unknown_model_are_rejected_before_generation(self):
        self.assertEqual(
            self.post("/generate", self.brief, {"Origin": "https://evil.test"}).status_code, 403
        )
        self.brief["model"] = "unknown"
        self.assertEqual(self.post("/generate", self.brief).status_code, 409)
        self.generator.assert_not_awaited()

    def test_replayed_request_does_not_call_provider_twice(self):
        self.generate()
        self.generate()
        self.assertEqual(self.generator.await_count, 1)

    def test_invalid_model_output_is_failed_not_published(self):
        self.generator.return_value = '{"evil":"not a course"}'
        key = self.generate()
        self.assertEqual(self.store.read(self.parent, key)["status"], "failed")
        self.assertEqual(self.engine.catalog(self.parent), [])

    def test_wrong_exercise_count_is_rejected(self):
        self.brief["exercises"] = 2
        key = self.generate()
        self.assertEqual(self.store.read(self.parent, key)["status"], "failed")

    def test_provider_error_is_redacted(self):
        self.generator.side_effect = RuntimeError("secret-token-and-private-url")
        key = self.generate()
        self.assertNotIn("secret", self.store.read(self.parent, key)["error"])

    def test_publication_requires_review_and_checks_exact_saved_version(self):
        key = self.generate()
        path = "/drafts/" + key + "/publish"
        self.assertEqual(self.post(path, {"version": 1, "reviewed": False}).status_code, 409)
        changed = copy.deepcopy(BUNDLE)
        changed["document"]["course"]["title"] = "New title"
        self.assertEqual(
            self.post("/drafts/" + key + "/save", {"version": 1, "bundle": changed}).status_code,
            200,
        )
        self.assertEqual(self.post(path, {"version": 1, "reviewed": True}).status_code, 409)
        published = self.post(path, {"version": 2, "reviewed": True})
        self.assertEqual(published.status_code, 200, published.text)
        self.checker.assert_called_once_with(
            self.parent, changed["document"]["course"]["lessons"][0], changed["solutions"]["stars"]
        )
        key2 = self.engine.publish(self.parent, changed["document"]["course"])
        self.assertEqual(published.json()["id"], key2)
        self.assertEqual(
            self.post("/drafts/" + key + "/save", {"version": 2, "bundle": BUNDLE}).status_code, 409
        )
        with self.engine.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM assignments").fetchone()[0], 0)

    def test_failed_reference_check_blocks_publication(self):
        key = self.generate()
        self.checker.side_effect = ValueError("Reference output does not match")
        response = self.post("/drafts/" + key + "/publish", {"version": 1, "reviewed": True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.engine.catalog(self.parent), [])

    def test_revision_preserves_original_and_sends_only_parent_draft(self):
        key = self.generate()
        self.brief.update(
            request_id=uuid.uuid4().hex,
            source=key,
            source_version=1,
            instructions="Use planets instead",
        )
        second = self.generate()
        self.assertNotEqual(key, second)
        self.assertEqual(self.generator.call_args.args[1]["previous_draft"], BUNDLE)
        self.assertEqual(self.store.read(self.parent, key)["bundle"], BUNDLE)

    def test_interrupted_job_expires_without_retry(self):
        store = Authoring(self.engine, clock=lambda: 1000)
        key = uuid.uuid4().hex
        store.start(self.parent, key, {"topic": "test"})
        later = Authoring(self.engine, clock=lambda: 1241)
        self.assertEqual(later.read(self.parent, key)["status"], "failed")
        self.generator.assert_not_awaited()

    def test_reference_checker_rejects_wrong_output_concepts_and_unsafe_code(self):
        lesson = BUNDLE["document"]["course"]["lessons"][0]
        runner = Mock()
        runner.run.return_value = SimpleNamespace(state="finished", output="7\n")
        self.assertEqual(
            check_reference(runner, lesson, BUNDLE["solutions"]["stars"]), {"checked": True}
        )
        runner.run.return_value = SimpleNamespace(state="finished", output="8\n")
        with self.assertRaises(ValueError):
            check_reference(runner, lesson, BUNDLE["solutions"]["stars"])
        with self.assertRaises(ValueError):
            check_reference(runner, lesson, "print(7)")
        runner.reset_mock()
        with self.assertRaises(ValueError):
            check_reference(runner, lesson, "import os")
        runner.run.assert_not_called()

    def test_missing_or_extra_solution_cannot_be_saved(self):
        for solution in [{}, {"stars": "print(7)", "extra": "print(0)"}]:
            bundle = copy.deepcopy(BUNDLE)
            bundle["solutions"] = solution
            with self.assertRaises(ValueError):
                validate_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
