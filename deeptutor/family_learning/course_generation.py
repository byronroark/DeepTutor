"""Use only the authenticated parent's provider. No learner data access."""

import json
from pathlib import Path

from deeptutor.multi_user.context import get_current_user_or_none
from deeptutor.services.codex_auth import get_codex_oauth_service
from deeptutor.services.llm.provider_core.openai_codex_provider import OpenAICodexProvider

from .generation_schema import schema


def parent_models(actor):
    user = get_current_user_or_none()
    if actor.role != "parent" or user is None or user.id != actor.id or user.role != "admin":
        raise PermissionError("Parent account context required")
    status = get_codex_oauth_service().public_status()
    return {"models": status["models"] if status["connection"] == "connected" else []}


async def generate_course(actor, brief):
    available = parent_models(actor)
    selection = next(
        (item for item in available["models"] if item["model"] == brief["model"]), None
    )
    if selection is None:
        raise ValueError("Selected parent model is unavailable. Refresh your connection.")
    rules = Path(__file__).with_name("authoring_prompt.txt").read_text()
    response = await OpenAICodexProvider().chat(
        messages=[
            {"role": "system", "content": rules},
            {"role": "user", "content": json.dumps(brief)},
        ],
        model=selection["model"],
        reasoning_effort=selection.get("reasoning_effort"),
        tools=None,
        tool_choice="none",
        text_format={
            "type": "json_schema",
            "name": "family_course",
            "strict": True,
            "schema": schema(),
        },
    )
    if response.finish_reason == "error" or not response.content:
        raise RuntimeError("Parent generation unavailable")
    if len(response.content.encode()) > 1_000_000:
        raise ValueError("AI draft was too large. Request fewer exercises.")
    result = json.loads(response.content)
    solutions = result.get("solutions")
    if not isinstance(solutions, list) or len({item["lesson_id"] for item in solutions}) != len(
        solutions
    ):
        raise ValueError("AI returned invalid or duplicate reference solutions")
    result["solutions"] = {item["lesson_id"]: item["code"] for item in solutions}
    return json.dumps(result)
