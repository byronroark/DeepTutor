"""Versioned, data-only course imports. Validation never executes lesson code."""

import json

from .local_lessons import validate
from .python_runner import validate_code

MAX_IMPORT_BYTES = 1_000_000


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError("Use ordinary JSON numbers, not NaN or Infinity")


def parse_document(raw):
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValueError("Course file must be at most 1 MB")
    try:
        document = json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=unique_object,
            parse_constant=invalid_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Use a UTF-8 JSON file without Markdown fences or commentary") from exc
    if not isinstance(document, dict) or set(document) != {"format", "version", "course"}:
        raise ValueError("File needs format, version and course fields")
    if (
        document["format"] != "family-learning-course"
        or type(document["version"]) is not int
        or document["version"] != 1
    ):
        raise ValueError("Use family-learning-course format version 1")
    course = document["course"]
    validate(course)
    for lesson in course["lessons"]:
        if lesson["kind"] == "python" and lesson.get("starter_code", "").strip():
            try:
                validate_code(lesson["starter_code"])
            except ValueError as exc:
                raise ValueError(f"Starter program in '{lesson['id']}': {exc}") from exc
    return course
