from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from deeptutor.family_learning.access import learner_route_allowed


class AccessTests(unittest.TestCase):
    def allowed(self, path, **extra):
        return learner_route_allowed(
            local_only=True, auth_enabled=True, role="user", path=path, **extra
        )

    def test_lessons_and_signout_allowed(self):
        for path in [
            "/api/family-learning",
            "/api/family-learning/courses/example",
            "/api/auth/me",
            "/api/auth/logout",
        ]:
            self.assertTrue(self.allowed(path))

    def test_other_surfaces_and_prefix_confusion_denied(self):
        for path in [
            "/api/settings",
            "/api/codex/models",
            "/api/sessions",
            "/api/chat",
            "/api/family-learning-evil",
            "/api/auth/users",
            "/ws",
        ]:
            self.assertFalse(self.allowed(path))

    def test_learner_websocket_denied(self):
        self.assertFalse(self.allowed("/ws", websocket=True))

    def test_admin_preserved_and_auth_disabled_refused(self):
        self.assertTrue(
            learner_route_allowed(
                local_only=True, auth_enabled=True, role="admin", path="/ws", websocket=True
            )
        )
        self.assertFalse(
            learner_route_allowed(
                local_only=True, auth_enabled=False, role="admin", path="/api/family-learning"
            )
        )
        self.assertTrue(
            learner_route_allowed(
                local_only=False, auth_enabled=False, role="user", path="/api/chat"
            )
        )


if __name__ == "__main__":
    unittest.main()
