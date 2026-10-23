"""Session-authenticated local lessons; Python delegates to a scoped host broker."""

import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .course_import import MAX_IMPORT_BYTES, parse_document
from .local_lessons import Actor


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(max_length=20000)
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=20000)


class PythonAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=16384)
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class Assignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    learner: str = Field(min_length=1, max_length=128)
    active: StrictBool = True


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: StrictBool
    feedback: str = Field(min_length=1, max_length=10000)


def origin(value):
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            return None
        return (
            parsed.scheme,
            parsed.hostname.lower(),
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
    except ValueError:
        return None


def create_router(
    require_auth, engine, enabled, allowed_origin, learner_accounts, python_executor=None
):
    router = APIRouter()

    async def actor(request: Request, token=Depends(require_auth)):
        if not enabled():
            raise HTTPException(404, "Family Learning is not enabled")
        # DeepTutor's auth-disabled mode returns None. It must never become an
        # implicit parent for private family records.
        if token is None or not getattr(token, "user_id", None):
            raise HTTPException(401, "A signed-in account is required")
        role = "parent" if getattr(token, "role", "") == "admin" else "learner"
        if request.method not in {"GET", "HEAD"}:
            configured = origin(allowed_origin())
            if configured is None or origin(request.headers.get("origin", "")) != configured:
                raise HTTPException(403, "Open Family Learning from its configured address")
            if (
                request.headers.get("content-type", "").split(";")[0].strip().lower()
                != "application/json"
            ):
                raise HTTPException(415, "JSON requests required")
        return Actor(token.user_id, role)

    async def parent(current=Depends(actor)):
        if current.role != "parent":
            raise HTTPException(403, "Parent administrator required")
        return current

    def perform(call):
        try:
            return call()
        except PermissionError as exc:
            raise HTTPException(403, "Course or submission unavailable") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (RuntimeError, OSError) as exc:
            raise HTTPException(
                503, "The local exercise service is not ready; ask your parent"
            ) from exc

    @router.get("")
    def overview(current=Depends(actor)):
        return {"role": current.role, "courses": perform(lambda: engine().catalog(current))}

    @router.get("/learners")
    def learners(current=Depends(parent)):
        return learner_accounts()

    @router.get("/starters")
    def starters(current=Depends(parent)):
        return json.loads(Path(__file__).with_name("starter_lessons.json").read_text())

    @router.post("/courses")
    def publish(body: dict, current=Depends(parent)):
        return {"id": perform(lambda: engine().publish(current, body))}

    async def imported_course(request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_IMPORT_BYTES:
                raise HTTPException(413, "Course file must be at most 1 MB")
        return perform(lambda: parse_document(bytes(raw)))

    @router.post("/imports/preview")
    async def import_preview(request: Request, current=Depends(parent)):
        return {"course": await imported_course(request)}

    @router.post("/imports/publish")
    async def import_publish(request: Request, current=Depends(parent)):
        course = await imported_course(request)
        return {"id": perform(lambda: engine().publish(current, course))}

    @router.get("/courses/{course}")
    def view(course: str, current=Depends(actor)):
        return perform(
            lambda: (
                engine().parent_course(current, course)
                if current.role == "parent"
                else engine().view(current, course)
            )
        )

    @router.post("/courses/{course}/assignment")
    def assign(course: str, body: Assignment, current=Depends(parent)):
        if body.learner not in {item["id"] for item in learner_accounts()}:
            raise HTTPException(403, "Select an enrolled learner")
        perform(lambda: engine().assign(current, course, body.learner, body.active))
        return {"saved": True}

    @router.post("/courses/{course}/lessons/{lesson}/answer")
    def answer(course: str, lesson: str, body: Answer, current=Depends(actor)):
        return perform(
            lambda: engine().respond(current, course, lesson, body.answer, body.request_id)
        )

    @router.post("/courses/{course}/lessons/{lesson}/draft")
    def draft(course: str, lesson: str, body: Draft, current=Depends(actor)):
        perform(lambda: engine().save_draft(current, course, lesson, body.text))
        return {"saved": True}

    @router.get("/courses/{course}/lessons/{lesson}/hint")
    def hint(course: str, lesson: str, index: int = 0, current=Depends(actor)):
        return perform(lambda: engine().coding_hint(current, course, lesson, index))

    @router.post("/courses/{course}/lessons/{lesson}/python")
    def python(course: str, lesson: str, body: PythonAnswer, current=Depends(actor)):
        def run():
            authority = engine()
            with authority.db() as db:
                _, _, item = authority.current(db, current, course, lesson)
                if item["kind"] != "python":
                    raise ValueError("This is not a Python exercise")
            if python_executor is None:
                raise RuntimeError("Python execution is not enabled")
            return python_executor(current, course, lesson, body.code, body.request_id)

        return perform(run)

    @router.post("/submissions/{submission}/review")
    def review(submission: str, body: Review, current=Depends(parent)):
        perform(lambda: engine().review(current, submission, body.approve, body.feedback))
        return {"saved": True}

    return router
