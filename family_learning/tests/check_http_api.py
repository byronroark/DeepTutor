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
                lambda: "http://testserver",
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

    def test_anonymous_auth_disabled_and_feature_disabled_fail_closed(self):
        self.signed_in = False
        self.assertEqual(self.client.get(self.base).status_code, 401)
        self.signed_in = True
        self.token = None
        self.assertEqual(self.client.get(self.base).status_code, 401)
        self.enabled = False
        self.assertEqual(self.client.get(self.base).status_code, 404)

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
