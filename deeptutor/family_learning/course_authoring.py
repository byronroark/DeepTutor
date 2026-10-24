"""Parent-owned draft lifecycle. Model output is data, never execution authority."""

import hashlib
import json
import re
import time

from .course_import import MAX_IMPORT_BYTES, invalid_constant, parse_document, unique_object
from .local_lessons import encoded
from .python_runner import validate_code


def validate_bundle(bundle):
    if not isinstance(bundle, dict) or set(bundle) != {"document", "solutions"}:
        raise ValueError("Draft needs a course document and private Python solutions")
    course = parse_document(encoded(bundle["document"]).encode())
    if len(course["lessons"]) > 8:
        raise ValueError("AI drafts support at most eight exercises")
    solutions = bundle["solutions"]
    ids = {item["id"] for item in course["lessons"] if item["kind"] == "python"}
    if not isinstance(solutions, dict) or set(solutions) != ids:
        raise ValueError("Provide one private reference solution for every Python exercise")
    for code in solutions.values():
        validate_code(code)
    if len(encoded(bundle).encode()) > MAX_IMPORT_BYTES:
        raise ValueError("Draft must be at most 1 MB")
    return bundle


def parse_generated(text):
    if len(text.encode()) > MAX_IMPORT_BYTES:
        raise ValueError("AI draft was too large. Request fewer exercises.")
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    try:
        bundle = json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError(
            "AI returned invalid JSON. Adjust the instructions and try again."
        ) from exc
    return validate_bundle(bundle)


class Authoring:
    def __init__(self, engine, clock=time.time):
        self.engine, self.clock = engine, clock
        with engine.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS course_drafts(
                id TEXT PRIMARY KEY, owner TEXT, status TEXT, version INTEGER,
                brief TEXT, bundle TEXT, error TEXT, created REAL, updated REAL,
                published TEXT)""")

    def parent(self, actor):
        if actor.role != "parent":
            raise PermissionError("Parent required")

    def read(self, actor, key):
        self.parent(actor)
        with self.engine.db() as db:
            row = db.execute(
                "SELECT * FROM course_drafts WHERE id=? AND owner=?", (key, actor.id)
            ).fetchone()
            if row is None:
                raise PermissionError("Draft unavailable")
            if row["status"] == "generating" and self.clock() - row["created"] > 240:
                db.execute(
                    "UPDATE course_drafts SET status='failed',error=? WHERE id=?",
                    (
                        "Generation was interrupted. Start a new draft; requests are not retried automatically.",
                        key,
                    ),
                )
                row = db.execute("SELECT * FROM course_drafts WHERE id=?", (key,)).fetchone()
        result = dict(row)
        result["brief"] = json.loads(result["brief"])
        result["bundle"] = json.loads(result["bundle"]) if result["bundle"] else None
        del result["owner"]
        return result

    def catalog(self, actor):
        self.parent(actor)
        with self.engine.db() as db:
            keys = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM course_drafts WHERE owner=? ORDER BY created DESC LIMIT 50",
                    (actor.id,),
                )
            ]
        return [self.read(actor, key) for key in keys]

    def start(self, actor, key, brief):
        self.parent(actor)
        if not re.fullmatch(r"[a-f0-9]{32}", key):
            raise ValueError("A unique request ID is required")
        now = self.clock()
        fingerprint = encoded(brief)
        with self.engine.db() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM course_drafts WHERE id=?", (key,)).fetchone()
            if prior:
                if prior["owner"] != actor.id or prior["brief"] != fingerprint:
                    raise ValueError("Request ID already used")
                return False
            if db.execute(
                "SELECT 1 FROM course_drafts WHERE owner=? AND status='generating' AND created>?",
                (actor.id, now - 240),
            ).fetchone():
                raise ValueError("A draft is already being generated. Open it below.")
            if (
                db.execute(
                    "SELECT count(*) FROM course_drafts WHERE owner=? AND created>?",
                    (actor.id, now - 3600),
                ).fetchone()[0]
                >= 12
            ):
                raise ValueError("Twelve draft requests were made this hour. Please try later.")
            db.execute(
                "INSERT INTO course_drafts VALUES(?,?,?,1,?,'','',?,?,'')",
                (key, actor.id, "generating", fingerprint, now, now),
            )
        return True

    def complete(self, actor, key, bundle=None, error=""):
        self.parent(actor)
        if bundle is not None:
            validate_bundle(bundle)
        with self.engine.db() as db:
            db.execute(
                "UPDATE course_drafts SET status=?,bundle=?,error=?,updated=? WHERE id=? AND owner=? AND status='generating'",
                (
                    "failed" if error else "ready",
                    encoded(bundle) if bundle else "",
                    error,
                    self.clock(),
                    key,
                    actor.id,
                ),
            )

    def save(self, actor, key, version, bundle):
        self.parent(actor)
        validate_bundle(bundle)
        with self.engine.db() as db:
            result = db.execute(
                "UPDATE course_drafts SET bundle=?,version=version+1,updated=? WHERE id=? AND owner=? AND version=? AND status='ready' AND published=''",
                (encoded(bundle), self.clock(), key, actor.id, version),
            )
            if result.rowcount != 1:
                raise ValueError("Draft changed or was published. Refresh before saving.")
        return self.read(actor, key)

    def publish(self, actor, key, version, check_python):
        draft = self.read(actor, key)
        if draft["status"] != "ready" or draft["version"] != version:
            raise ValueError("Draft changed. Refresh and review it again.")
        if draft["published"]:
            return {"id": draft["published"]}
        bundle = validate_bundle(draft["bundle"])
        for lesson in bundle["document"]["course"]["lessons"]:
            if lesson["kind"] == "python":
                if check_python is None:
                    raise RuntimeError("Python sandbox checks are unavailable")
                check_python(actor, lesson, bundle["solutions"][lesson["id"]])
        with self.engine.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM course_drafts WHERE id=? AND owner=?", (key, actor.id)
            ).fetchone()
            if row["version"] != version:
                raise ValueError("Draft changed during checks. Review it again.")
            content = encoded(bundle["document"]["course"])
            course_id = hashlib.sha256((actor.id + "\0" + content).encode()).hexdigest()
            db.execute(
                "INSERT OR IGNORE INTO courses VALUES(?,?,?)", (course_id, actor.id, content)
            )
            db.execute("UPDATE course_drafts SET published=? WHERE id=?", (course_id, key))
        return {"id": course_id}
