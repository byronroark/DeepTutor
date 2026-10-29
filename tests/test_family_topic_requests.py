from pathlib import Path
import tempfile

import pytest

from deeptutor.family_learning.local_lessons import Actor
from deeptutor.family_learning.topic_requests import Topics


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as root:
        yield Topics(Path(root))


def test_learner_request_is_idempotent_and_scoped(store):
    learner = Actor("child-one", "learner")
    row = store.ask(learner, "a" * 32, "Python robots")
    assert row["status"] == "pending"
    assert store.ask(learner, "a" * 32, "Python robots") == row
    assert store.list(Actor("other-child", "learner")) == []
    with pytest.raises(ValueError):
        store.ask(learner, "a" * 32, "Different topic")
    with pytest.raises(PermissionError):
        store.ask(Actor("dad", "parent"), "b" * 32, "A topic")


def test_parent_can_edit_once_and_learner_cannot_decide(store):
    learner = Actor("child", "learner")
    parent = Actor("dad", "parent")
    store.ask(learner, "a" * 32, "Python robots")
    with pytest.raises(PermissionError):
        store.decide(learner, "a" * 32, "approve", "Python robots")
    with pytest.raises(ValueError):
        store.decide(parent, "a" * 32, "approve", "Changed snapshot")
    result = store.decide(parent, "a" * 32, "approve", "Python robots", "Python variables")
    assert result["status"] == "approved" and result["approved_topic"] == "Python variables"
    with pytest.raises(ValueError):
        store.decide(parent, "a" * 32, "deny", "Python robots")


def test_deny_and_rate_limit(store):
    learner = Actor("child", "learner")
    parent = Actor("mom", "parent")
    store.ask(learner, "a" * 32, "Ancient Egypt")
    with pytest.raises(ValueError):
        store.ask(learner, "b" * 32, "More history")
    assert store.decide(parent, "a" * 32, "deny", "Ancient Egypt")["status"] == "denied"
