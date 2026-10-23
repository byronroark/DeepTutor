"""Check draft reference programs with the same isolated runner as learners."""

import ast

from .python_runner import validate_code


def check_reference(runner, lesson, code):
    validate_code(code)
    nodes = list(ast.walk(ast.parse(code)))
    present = {
        label
        for label, kind in [
            ("assignment", ast.Assign),
            ("for_loop", ast.For),
            ("while_loop", ast.While),
        ]
        if any(isinstance(node, kind) for node in nodes)
    }
    if not set(lesson.get("requirements", [])) <= present:
        raise ValueError("Reference solution is missing a required Python concept")
    result = runner.run(code)
    if result.state != "finished":
        raise ValueError("Reference solution did not finish successfully in the sandbox")

    def normalize(text):
        return text.replace("\r\n", "\n").rstrip("\n")

    if normalize(result.output) != normalize(lesson["expected_output"]):
        raise ValueError("Reference solution output does not match the exercise expectation")
    return {"checked": True}
