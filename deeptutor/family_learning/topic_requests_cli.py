"""Fixed local bridge entry point; installed SSH/sudo endpoint supplies trust."""

import json
import sys

from deeptutor.family_learning.local_lessons import Actor
from deeptutor.family_learning.topic_requests import Topics
from deeptutor.multi_user.paths import SYSTEM_ROOT


def main():
    raw = sys.stdin.buffer.read(4097)
    if len(raw) > 4096:
        raise ValueError("Topic operation too large")
    value = json.loads(raw)
    store = Topics(SYSTEM_ROOT / "family-learning")
    if value == {"op": "topic-pending"}:
        return {"requests": store.list(Actor("discord", "parent"), pending=True)}
    if (
        isinstance(value, dict)
        and set(value) == {"op", "id", "decision", "expected_topic", "replacement", "parent"}
        and value["op"] == "topic-decision"
        and value["parent"] in ["dad", "mom"]
    ):
        return store.decide(
            Actor("discord:" + value["parent"], "parent"),
            value["id"],
            value["decision"],
            value["expected_topic"],
            value["replacement"],
        )
    raise ValueError("Topic operation not permitted")


if __name__ == "__main__":
    try:
        print(json.dumps({"ok": True, "result": main()}))
    except (OSError, ValueError, PermissionError, KeyError, TypeError):
        print(json.dumps({"ok": False, "error": "Topic request unavailable or already reviewed"}))
        sys.exit(1)
