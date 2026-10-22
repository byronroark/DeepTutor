"""Assignment-aware Python grading on the trusted runner host."""

import ast
import json
import re
import time

from .local_lessons import Actor, encoded


class PythonGrader:
    def __init__(self, engine, runner, clock=time.time):
        self.engine, self.runner, self.clock = engine, runner, clock
        with engine.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS python_jobs(
                id TEXT PRIMARY KEY, learner TEXT, course TEXT, lesson TEXT,
                fingerprint TEXT, epoch INTEGER, created REAL, state TEXT)""")

    def run(self, learner, course, lesson, code, request_id):
        if not isinstance(learner, str) or not 1 <= len(learner) <= 128:
            raise ValueError("Invalid learner")
        if not isinstance(code, str) or not code.strip() or len(code.encode()) > 16384:
            raise ValueError("Write a program of at most 16 KB")
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{32}", request_id):
            raise ValueError("A unique request ID is required")
        actor = Actor(learner, "learner")
        fingerprint = encoded([course, lesson, code])
        now = self.clock()
        with self.engine.db() as db:
            db.execute("BEGIN IMMEDIATE")
            _, _, item = self.engine.current(db, actor, course, lesson)
            if item["kind"] != "python":
                raise ValueError("This is not a Python exercise")
            epoch = db.execute(
                "SELECT epoch FROM assignments WHERE course=? AND learner=?", (course, learner)
            ).fetchone()["epoch"]
            prior = db.execute("SELECT * FROM events WHERE id=?", (request_id,)).fetchone()
            if prior:
                if prior["actor"] != learner or prior["fingerprint"] != fingerprint:
                    raise ValueError("Request ID already used")
                return json.loads(prior["result"])
            if db.execute("SELECT 1 FROM python_jobs WHERE id=?", (request_id,)).fetchone():
                raise ValueError(
                    "This run is pending or was interrupted. Ask your parent before retrying."
                )
            if db.execute(
                "SELECT 1 FROM work WHERE course=? AND learner=? AND lesson=? AND state IN ('passed','review')",
                (course, learner, lesson),
            ).fetchone():
                raise ValueError("This exercise is already complete")
            if db.execute(
                "SELECT 1 FROM python_jobs WHERE learner=? AND state='running'", (learner,)
            ).fetchone():
                raise ValueError("A program is already running. If interrupted, ask your parent.")
            if (
                db.execute(
                    "SELECT count(*) FROM python_jobs WHERE learner=? AND created>=?",
                    (learner, now - 60),
                ).fetchone()[0]
                >= 10
            ):
                raise ValueError("Take a moment before running another program.")
            db.execute(
                "INSERT INTO python_jobs VALUES(?,?,?,?,?,?,?,?)",
                (request_id, learner, course, lesson, fingerprint, epoch, now, "running"),
            )
        try:
            try:
                execution = self.runner.run(code)
                run_state, output = execution.state, execution.output
            except ValueError as error:
                run_state, output = "syntax_feedback", str(error)
            if (
                run_state
                not in {"finished", "error", "time_limit", "output_limit", "syntax_feedback"}
                or len(output.encode()) > 65536
            ):
                raise RuntimeError("Invalid isolated runner result")
            requirements_ok = False
            if run_state == "finished":
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
                requirements_ok = set(item.get("requirements", [])) <= present
            passed = (
                run_state == "finished"
                and requirements_ok
                and output.replace("\r\n", "\n").rstrip("\n")
                == item["expected_output"].replace("\r\n", "\n").rstrip("\n")
            )
            rejected = False
            with self.engine.db() as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    self.engine.current(db, actor, course, lesson)
                    current_epoch = db.execute(
                        "SELECT epoch FROM assignments WHERE course=? AND learner=?",
                        (course, learner),
                    ).fetchone()["epoch"]
                    if current_epoch != epoch:
                        raise PermissionError("Assignment changed during execution")
                except PermissionError:
                    db.execute(
                        "UPDATE python_jobs SET state='invalidated' WHERE id=?", (request_id,)
                    )
                    rejected = True
                else:
                    db.execute(
                        "INSERT OR IGNORE INTO work(course,learner,lesson) VALUES(?,?,?)",
                        (course, learner, lesson),
                    )
                    attempts = (
                        db.execute(
                            "SELECT attempts FROM work WHERE course=? AND learner=? AND lesson=?",
                            (course, learner, lesson),
                        ).fetchone()["attempts"]
                        + 1
                    )
                    hints = item["hints"] or ["Check the example, or ask your parent for help."]
                    result = {
                        "state": "passed" if passed else "retry",
                        "feedback": item["success"]
                        if passed
                        else hints[min(attempts - 1, len(hints) - 1)],
                        "execution": run_state,
                        "output": output,
                    }
                    db.execute(
                        "UPDATE work SET attempts=?,state=?,draft=?,feedback=? WHERE course=? AND learner=? AND lesson=?",
                        (
                            attempts,
                            result["state"],
                            code,
                            result["feedback"],
                            course,
                            learner,
                            lesson,
                        ),
                    )
                    db.execute(
                        "INSERT INTO events VALUES(?,?,?,?)",
                        (request_id, learner, fingerprint, encoded(result)),
                    )
                    db.execute("UPDATE python_jobs SET state='finished' WHERE id=?", (request_id,))
            if rejected:
                raise PermissionError("Assignment changed; the result was discarded")
            return result
        except Exception:
            with self.engine.db() as db:
                db.execute(
                    "UPDATE python_jobs SET state='failed' WHERE id=? AND state='running'",
                    (request_id,),
                )
            raise
