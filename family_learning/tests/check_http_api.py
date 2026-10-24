import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from deeptutor.family_learning.http_api import create_router
from deeptutor.family_learning.local_lessons import Actor, Lessons


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = Lessons(self.temp.name)
        self.token = SimpleNamespace(user_id="parent-a", role="admin")
        self.enabled = True
        self.signed_in = True
        self.allowed_origin = "http://testserver"
        self.python_executor = Mock(side_effect=RuntimeError("Disabled"))

        async def auth():
            if not self.signed_in:
                raise HTTPException(401, "Sign in")
            return self.token

        app = FastAPI()
        app.include_router(
            create_router(
                auth,
                lambda: self.engine,
                lambda: self.enabled,
                lambda: self.allowed_origin,
                lambda: [{"id": "child-a", "username": "Learner"}],
                python_executor=self.python_executor,
            ),
            prefix="/api/family-learning",
        )
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.base = "/api/family-learning"
        self.course = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "deeptutor/family_learning/starter_lessons.json"
            ).read_text()
        )[0]
        self.headers = {"Origin": "http://testserver"}

    def test_explicit_lan_and_local_origins_only(self):
        self.allowed_origin = "http://testserver,http://192.168.1.221:3785"
        for value in ["http://testserver", "http://192.168.1.221:3785"]:
            response = self.client.post(
                self.base + "/courses", json=self.course, headers={"Origin": value}
            )
            self.assertEqual(response.status_code, 200, response.text)
        for value in ["http://192.168.1.222:3785", "http://192.168.1.221.evil:3785", "null"]:
            self.assertEqual(
                self.client.post(
                    self.base + "/courses", json=self.course, headers={"Origin": value}
                ).status_code,
                403,
            )

    def test_export_contains_only_the_course_and_requires_its_parent_owner(self):
        published = self.client.post(self.base + "/courses", json=self.course, headers=self.headers)
        key = published.json()["id"]
        exported = self.client.get(self.base + "/courses/" + key + "/export")
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(
            exported.json(),
            {"format": "family-learning-course", "version": 1, "course": self.course},
        )
        self.token = SimpleNamespace(user_id="child-a", role="user")
        self.assertEqual(
            self.client.get(self.base + "/courses/" + key + "/export").status_code, 403
        )
        self.token = SimpleNamespace(user_id="other-parent", role="admin")
        self.assertEqual(
            self.client.get(self.base + "/courses/" + key + "/export").status_code, 403
        )

    def publish_assign(self):
        published = self.client.post(self.base + "/courses", json=self.course, headers=self.headers)
        self.assertEqual(published.status_code, 200, published.text)
        key = published.json()["id"]
        assigned = self.client.post(
            f"{self.base}/courses/{key}/assignment",
            json={"learner": "child-a"},
            headers=self.headers,
        )
        self.assertEqual(assigned.status_code, 200)
        return key

    def test_retake_is_parent_only_and_history_reaches_learner(self):
        key = self.publish_assign()
        self.engine.respond(Actor("child-a", "learner"), key, "name-a-value", "0", uuid.uuid4().hex)
        body = {
            "learner": "child-a",
            "lesson": None,
            "expected_epoch": 0,
            "request_id": uuid.uuid4().hex,
        }
        path = f"{self.base}/courses/{key}/retake"
        self.token = SimpleNamespace(user_id="child-a", role="user")
        self.assertEqual(self.client.post(path, json=body, headers=self.headers).status_code, 403)
        self.token = SimpleNamespace(user_id="parent-a", role="admin")
        self.assertEqual(
            self.client.post(
                path, json=body, headers={"Origin": "http://other.example"}
            ).status_code,
            403,
        )
        response = self.client.post(path, json=body, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            self.client.post(path, json=body, headers=self.headers).json(), response.json()
        )
        self.token = SimpleNamespace(user_id="child-a", role="user")
        view = self.client.get(f"{self.base}/courses/{key}").json()
        self.assertEqual(view["lessons"][0]["state"], "new")
        self.assertEqual(view["history"][0]["results"][0]["state"], "passed")

    def test_import_preview_publish_and_no_automatic_assignment(self):
        document = {"format": "family-learning-course", "version": 1, "course": self.course}
        path = self.base + "/imports/"
        preview = self.client.post(path + "preview", json=document, headers=self.headers)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["course"], self.course)
        self.assertEqual(self.engine.catalog(Actor("parent-a", "parent")), [])
        saved = self.client.post(path + "publish", json=document, headers=self.headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(
            self.client.post(path + "publish", json=document, headers=self.headers).json(),
            saved.json(),
        )
        with self.engine.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM courses").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM assignments").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM work").fetchone()[0], 0)
        self.python_executor.assert_not_called()
        self.token = SimpleNamespace(user_id="child-a", role="user")
        for action in ("preview", "publish"):
            self.assertEqual(
                self.client.post(path + action, json=document, headers=self.headers).status_code,
                403,
            )

    def test_import_rejects_invalid_versions_json_and_oversized_files(self):
        path = self.base + "/imports/preview"
        for text in [
            "```json\n{}\n```",
            '{"format":"family-learning-course","version":1,"version":1,"course":{}}',
            json.dumps(
                {"format": "family-learning-course", "version": True, "course": self.course}
            ),
            json.dumps({"format": "family-learning-course", "version": 2, "course": self.course}),
        ]:
            response = self.client.post(
                path, content=text, headers={**self.headers, "Content-Type": "application/json"}
            )
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            self.client.post(
                path,
                content=" " * 1_000_001,
                headers={**self.headers, "Content-Type": "application/json"},
            ).status_code,
            413,
        )
        self.assertEqual(self.engine.catalog(Actor("parent-a", "parent")), [])

    def test_import_refuses_unsupported_python_without_executing_it(self):
        lesson = self.course["lessons"][0]
        lesson.update(kind="python", expected_output="", starter_code="import os", requirements=[])
        lesson.pop("answer", None)
        lesson.pop("choices", None)
        response = self.client.post(
            self.base + "/imports/preview",
            json={"format": "family-learning-course", "version": 1, "course": self.course},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("Starter program", response.json()["detail"])
        self.python_executor.assert_not_called()

    def test_anonymous_auth_disabled_and_feature_disabled_fail_closed(self):
        self.signed_in = False
        self.assertEqual(self.client.get(self.base).status_code, 401)
        self.signed_in = True
        self.token = None
        self.assertEqual(self.client.get(self.base).status_code, 401)
        self.enabled = False
        self.assertEqual(self.client.get(self.base).status_code, 404)

    def test_coding_hint_is_assigned_read_only_and_does_not_run_code(self):
        lesson = self.course["lessons"][0]
        lesson.update(
            kind="python",
            expected_output="7",
            starter_code="print(7)",
            requirements=[],
            hints=["Use print.", "Keep your indentation."],
        )
        lesson.pop("answer", None)
        lesson.pop("choices", None)
        key = self.publish_assign()
        self.token = SimpleNamespace(user_id="child-a", role="user")
        path = f"{self.base}/courses/{key}/lessons/{lesson['id']}/hint"
        self.assertEqual(self.client.get(path).json(), {"hint": "Use print.", "has_more": True})
        self.assertEqual(
            self.client.get(path + "?index=1").json(),
            {"hint": "Keep your indentation.", "has_more": False},
        )
        self.assertEqual(self.client.get(path + "?index=-1").status_code, 409)
        locked = self.course["lessons"][1]["id"]
        self.assertEqual(
            self.client.get(f"{self.base}/courses/{key}/lessons/{locked}/hint").status_code, 403
        )
        with self.engine.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM work").fetchone()[0], 0)
        self.python_executor.assert_not_called()
        self.token = SimpleNamespace(user_id="other-child", role="user")
        self.assertEqual(self.client.get(path).status_code, 403)

    def test_csrf_and_form_submission_refused(self):
        for headers in [
            {},
            {"Origin": "http://evil.example"},
            {"Origin": "http://testserver.evil.example"},
        ]:
            self.assertEqual(
                self.client.post(
                    self.base + "/courses", json=self.course, headers=headers
                ).status_code,
                403,
            )
        self.assertEqual(
            self.client.post(
                self.base + "/courses",
                content=json.dumps(self.course),
                headers={**self.headers, "Content-Type": "text/plain"},
            ).status_code,
            415,
        )

    def test_learner_cannot_publish_fetch_starters_or_enumerate_accounts(self):
        self.token = SimpleNamespace(user_id="child-a", role="user")
        self.assertEqual(
            self.client.post(
                self.base + "/courses", json=self.course, headers=self.headers
            ).status_code,
            403,
        )
        for endpoint in ["/starters", "/learners"]:
            self.assertEqual(self.client.get(self.base + endpoint).status_code, 403)

    def test_assignment_ignores_request_identity_and_checks_enrollment(self):
        key = self.publish_assign()
        response = self.client.post(
            f"{self.base}/courses/{key}/assignment",
            json={"learner": "stranger"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 403)
        self.token = SimpleNamespace(user_id="child-a", role="user")
        path = f"{self.base}/courses/{key}/lessons/name-a-value/answer"
        self.assertEqual(
            self.client.post(
                path,
                json={"answer": "0", "request_id": uuid.uuid4().hex, "role": "admin"},
                headers=self.headers,
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                path, json={"answer": "0", "request_id": uuid.uuid4().hex}, headers=self.headers
            ).json()["state"],
            "passed",
        )

    def test_private_views_cross_account_and_revocation(self):
        key = self.publish_assign()
        self.token = SimpleNamespace(user_id="child-a", role="user")
        view = self.client.get(f"{self.base}/courses/{key}").json()
        self.assertNotIn("answer", view["lessons"][0])
        self.token = SimpleNamespace(user_id="child-b", role="user")
        self.assertEqual(self.client.get(f"{self.base}/courses/{key}").status_code, 403)

    def test_python_run_requires_assignment_and_server_identity(self):
        self.course = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "deeptutor/family_learning/starter_lessons.json"
            ).read_text()
        )[3]
        key = self.publish_assign()
        self.token = SimpleNamespace(user_id="child-a", role="user")
        path = f"{self.base}/courses/{key}/lessons/variable-program/python"
        body = {"code": "stars = 5\nprint(stars + 2)", "request_id": uuid.uuid4().hex}
        self.assertEqual(self.client.post(path, json=body, headers=self.headers).status_code, 503)
        self.python_executor.reset_mock()
        self.assertEqual(
            self.client.post(
                path, json={**body, "learner": "other-child"}, headers=self.headers
            ).status_code,
            422,
        )
        self.python_executor.assert_not_called()
        self.python_executor.side_effect = None
        self.python_executor.return_value = {
            "state": "passed",
            "feedback": "Good job",
            "output": "7\n",
            "execution": "finished",
        }
        self.assertEqual(self.client.post(path, json=body, headers=self.headers).status_code, 200)
        self.assertEqual(self.python_executor.call_args.args[0], Actor("child-a", "learner"))
        self.token = SimpleNamespace(user_id="other-child", role="user")
        self.python_executor.reset_mock()
        self.assertEqual(self.client.post(path, json=body, headers=self.headers).status_code, 403)
        self.python_executor.assert_not_called()

    def test_writing_submission_revision_and_approval_through_http(self):
        self.course = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "deeptutor/family_learning/starter_lessons.json"
            ).read_text()
        )[2]
        key = self.publish_assign()
        self.token = SimpleNamespace(user_id="child-a", role="user")
        path = f"{self.base}/courses/{key}/lessons/book-report"
        self.assertEqual(
            self.client.post(
                path + "/draft", json={"text": "Saved locally"}, headers=self.headers
            ).status_code,
            200,
        )
        first = self.client.post(
            path + "/answer",
            json={"answer": "My report", "request_id": uuid.uuid4().hex},
            headers=self.headers,
        ).json()
        review = f"{self.base}/submissions/{first['submission']}/review"
        self.assertEqual(
            self.client.post(
                review, json={"approve": True, "feedback": "My own approval"}, headers=self.headers
            ).status_code,
            403,
        )
        self.token = SimpleNamespace(user_id="parent-a", role="admin")
        self.assertEqual(
            self.client.post(
                review,
                json={"approve": False, "feedback": "Please add an example."},
                headers=self.headers,
            ).status_code,
            200,
        )
        self.token = SimpleNamespace(user_id="child-a", role="user")
        second = self.client.post(
            path + "/answer",
            json={"answer": "My revised report with an example", "request_id": uuid.uuid4().hex},
            headers=self.headers,
        ).json()
        self.token = SimpleNamespace(user_id="parent-a", role="admin")
        self.assertEqual(
            self.client.post(
                f"{self.base}/submissions/{second['submission']}/review",
                json={"approve": True, "feedback": "Your example supports your opinion."},
                headers=self.headers,
            ).status_code,
            200,
        )
        self.token = SimpleNamespace(user_id="child-a", role="user")
        self.assertEqual(
            self.client.get(f"{self.base}/courses/{key}").json()["lessons"][0]["state"], "passed"
        )
        self.token = SimpleNamespace(user_id="parent-b", role="admin")
        self.assertEqual(self.client.get(f"{self.base}/courses/{key}").status_code, 403)
        self.engine.assign(Actor("parent-a", "parent"), key, "child-a", False)
        self.token = SimpleNamespace(user_id="child-a", role="user")
        self.assertEqual(self.client.get(self.base).json()["courses"], [])
        self.assertEqual(self.client.get(f"{self.base}/courses/{key}").status_code, 403)


if __name__ == "__main__":
    unittest.main()
