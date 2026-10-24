"""Strict provider output schema; local validation remains authoritative."""


def obj(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


TEXT = {"type": "string"}
TEXTS = {"type": "array", "items": TEXT}


def schema():
    common = {
        "id": TEXT,
        "title": TEXT,
        "explanation": TEXT,
        "question": TEXT,
        "hints": TEXTS,
        "success": TEXT,
    }
    variants = []
    for kind, extra in [
        ("choice", {"choices": TEXTS, "answer": {"type": "integer"}}),
        ("number", {"answer": TEXT}),
        ("writing", {"rubric": TEXTS}),
        (
            "python",
            {
                "starter_code": TEXT,
                "expected_output": TEXT,
                "requirements": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["assignment", "for_loop", "while_loop"]},
                },
            },
        ),
    ]:
        variants.append(obj({**common, "kind": {"type": "string", "enum": [kind]}, **extra}))
    course = obj(
        {
            "title": TEXT,
            "subject": TEXT,
            "objectives": TEXTS,
            "lessons": {"type": "array", "items": {"anyOf": variants}},
        }
    )
    return obj(
        {
            "document": obj(
                {
                    "format": {"type": "string", "enum": ["family-learning-course"]},
                    "version": {"type": "integer", "enum": [1]},
                    "course": course,
                }
            ),
            "solutions": {"type": "array", "items": obj({"lesson_id": TEXT, "code": TEXT})},
        }
    )
