"""Parent-only authoring routes, separate from all learner work."""

import asyncio
import json

from fastapi import BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .course_authoring import Authoring, parse_generated


class Brief(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    topic: str = Field(min_length=1, max_length=200)
    level: str = Field(min_length=1, max_length=200)
    goals: str = Field(min_length=1, max_length=2000)
    exercises: int = Field(ge=1, le=8, strict=True)
    minutes: int = Field(ge=5, le=60, strict=True)
    kinds: list[str] = Field(min_length=1, max_length=4)
    instructions: str = Field(default="", max_length=2000)
    model: str = Field(min_length=1, max_length=150)
    source: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    source_version: int | None = Field(default=None, ge=1, strict=True)


class SaveDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, strict=True)
    bundle: dict


class PublishDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, strict=True)
    reviewed: bool


def attach_authoring(router, parent, engine, perform, generator, models, checker):
    def authority():
        return Authoring(engine())

    @router.get("/authoring/models")
    def available_models(current=Depends(parent)):
        return models(current) if models else {"models": []}

    @router.get("/authoring/drafts")
    def drafts(current=Depends(parent)):
        return perform(lambda: authority().catalog(current))

    @router.get("/authoring/drafts/{key}")
    def draft(key: str, current=Depends(parent)):
        return perform(lambda: authority().read(current, key))

    @router.post("/authoring/generate", status_code=202)
    async def generate(body: Brief, tasks: BackgroundTasks, current=Depends(parent)):
        if generator is None:
            raise HTTPException(503, "Parent course generation is unavailable")
        if set(body.kinds) - {"python", "number", "choice", "writing"}:
            raise HTTPException(422, "Select supported exercise types")
        options = models(current) if models else {"models": []}
        if body.model not in {item["model"] for item in options["models"]}:
            raise HTTPException(
                409, "Connect your parent OpenAI account and select an available model"
            )
        brief = body.model_dump(exclude={"request_id"})
        if body.source:
            prior = perform(lambda: authority().read(current, body.source))
            if prior["status"] != "ready" or prior["version"] != body.source_version:
                raise HTTPException(409, "Save and refresh the source draft before revising")
            brief["previous_draft"] = prior["bundle"]
        started = perform(lambda: authority().start(current, body.request_id, brief))

        async def work():
            try:
                text = await asyncio.wait_for(generator(current, brief), timeout=180)
                bundle = parse_generated(text)
                course = bundle["document"]["course"]
                if len(course["lessons"]) != body.exercises or any(
                    item["kind"] not in body.kinds for item in course["lessons"]
                ):
                    raise ValueError(
                        "AI draft did not match the requested exercise count or types. Please try revised instructions."
                    )
                authority().complete(current, body.request_id, bundle)
            except ValueError as error:
                authority().complete(current, body.request_id, error=str(error)[:500])
            except Exception:
                # Never persist provider errors, responses, tokens, or user identity.
                authority().complete(
                    current,
                    body.request_id,
                    error="Generation could not finish. Check your parent connection and try a new draft. Your other drafts are safe.",
                )

        if started:
            tasks.add_task(work)
        return {"id": body.request_id}

    @router.post("/authoring/drafts/{key}/save")
    async def save(key: str, request: Request, current=Depends(parent)):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 1_050_000:
                raise HTTPException(413, "Draft must be at most 1 MB")
        try:
            body = SaveDraft.model_validate(json.loads(raw))
        except ValueError as error:
            raise HTTPException(422, "Use a valid draft document and version") from error
        return perform(lambda: authority().save(current, key, body.version, body.bundle))

    @router.post("/authoring/drafts/{key}/publish")
    def publish(key: str, body: PublishDraft, current=Depends(parent)):
        if body.reviewed is not True:
            raise HTTPException(409, "Review this draft before publishing")
        return perform(lambda: authority().publish(current, key, body.version, checker))
