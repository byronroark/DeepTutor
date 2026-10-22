"""Opt-in Family Learning integration; existing deployments remain disabled."""

import os

from deeptutor.api.routers.auth import require_auth
from deeptutor.family_learning.http_api import create_router
from deeptutor.family_learning.local_lessons import Lessons
from deeptutor.family_learning.python_client import run_python
from deeptutor.multi_user.paths import SYSTEM_ROOT
from deeptutor.services.auth import list_users


def learner_accounts():
    return [
        {"id": item["id"], "username": item["username"]}
        for item in list_users()
        if item.get("role") != "admin" and item.get("preset") == "learner"
    ]


def execute_python(actor, course, lesson, code, request_id):
    if os.environ.get("FAMILY_PYTHON_ENABLED") != "1":
        raise RuntimeError("Python execution is disabled")
    return run_python(
        os.environ.get("FAMILY_PYTHON_SOCKET", "/run/family-python/broker.sock"),
        os.environ.get("FAMILY_PYTHON_TOKEN", "/run/family-python/token"),
        actor,
        course,
        lesson,
        code,
        request_id,
    )


router = create_router(
    require_auth=require_auth,
    engine=lambda: Lessons(SYSTEM_ROOT / "family-learning"),
    enabled=lambda: os.environ.get("FAMILY_LEARNING_ENABLED") == "1",
    allowed_origin=lambda: os.environ.get("FAMILY_LEARNING_ORIGIN", ""),
    learner_accounts=learner_accounts,
    python_executor=execute_python,
)
