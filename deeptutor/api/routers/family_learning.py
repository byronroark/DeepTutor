"""Opt-in Family Learning integration; existing deployments remain disabled."""

import os

from deeptutor.api.routers.auth import require_auth
from deeptutor.family_learning.http_api import create_router
from deeptutor.family_learning.local_lessons import Lessons
from deeptutor.multi_user.paths import SYSTEM_ROOT
from deeptutor.services.auth import list_users


def learner_accounts():
    return [
        {"id": item["id"], "username": item["username"]}
        for item in list_users()
        if item.get("role") != "admin" and item.get("preset") == "learner"
    ]


router = create_router(
    require_auth=require_auth,
    engine=lambda: Lessons(SYSTEM_ROOT / "family-learning"),
    enabled=lambda: os.environ.get("FAMILY_LEARNING_ENABLED") == "1",
    allowed_origin=lambda: os.environ.get("FAMILY_LEARNING_ORIGIN", ""),
    learner_accounts=learner_accounts,
)
