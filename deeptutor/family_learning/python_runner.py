"""Host-side disposable Python runner. Never give the web app a Docker socket.

This is not yet wired to HTTP or learner submissions. Syntax checks support
lesson scope; container isolation and resource limits are the security boundary.
"""

import ast
from dataclasses import dataclass
import math
import selectors
import shutil
import subprocess
import threading
import time
import uuid

IMAGE = "python@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2"
SLOTS = threading.BoundedSemaphore(2)
UNHEALTHY = threading.Event()
FUNCTIONS = {"print", "range", "len", "str", "int", "float", "round", "min", "max", "sum", "abs"}
NODES = {
    ast.Module,
    ast.Expr,
    ast.Assign,
    ast.AugAssign,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.UnaryOp,
    ast.UAdd,
    ast.USub,
    ast.Not,
    ast.Call,
    ast.For,
    ast.While,
    ast.If,
    ast.Break,
    ast.Continue,
    ast.Pass,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.List,
    ast.Tuple,
    ast.Subscript,
    ast.Slice,
}


def validate_code(code):
    if not isinstance(code, str) or not code.strip() or len(code.encode()) > 16384:
        raise ValueError("Write a program of at most 16 KB.")
    try:
        tree = ast.parse(code)
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("Check the spelling, brackets and indentation in your program.") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 2048:
        raise ValueError("Try a smaller program.")
    for node in nodes:
        if type(node) not in NODES:
            raise ValueError(
                "This lesson supports variables, arithmetic, choices, loops and printing."
            )
        if isinstance(node, ast.Name) and (
            node.id.startswith("_") or (isinstance(node.ctx, ast.Store) and node.id in FUNCTIONS)
        ):
            raise ValueError("Choose another variable name.")
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords
        ):
            raise ValueError("Use only the functions available in this lesson.")
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str) and len(node.value) > 4096:
                raise ValueError("Try shorter text.")
            if isinstance(node.value, int) and node.value.bit_length() > 2048:
                raise ValueError("Try a smaller number.")
            if (
                isinstance(node.value, (complex, bytes))
                or isinstance(node.value, float)
                and not math.isfinite(node.value)
            ):
                raise ValueError("Use ordinary numbers and text in this lesson.")


@dataclass(frozen=True)
class Result:
    state: str
    output: str
    exit_code: int | None


class PythonRunner:
    def __init__(self):
        self.docker = shutil.which("docker")
        if not self.docker:
            raise RuntimeError("The parent has not installed the local Python runner.")

    def run(self, code):
        validate_code(code)
        return self._isolated(code)

    def _isolated(self, code):
        """Private isolation primitive; only run() may serve learner programs."""
        if len(code.encode()) > 16384:
            raise ValueError("Program too large")
        if UNHEALTHY.is_set():
            raise RuntimeError("Runner cleanup needs parent inspection before another exercise.")
        if not SLOTS.acquire(blocking=False):
            raise RuntimeError("Two exercises are running. Try again in a moment.")
        name = "family-python-" + uuid.uuid4().hex
        command = [
            self.docker,
            "create",
            "--pull=never",
            "--rm",
            "-i",
            "--name",
            name,
            "--label",
            "org.family-learning.runner=1",
            "--log-driver",
            "none",
            "--network",
            "none",
            "--ipc",
            "none",
            "--cgroupns",
            "private",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            "65534:65534",
            "--workdir",
            "/tmp",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777",
            "--memory",
            "128m",
            "--memory-swap",
            "128m",
            "--cpus",
            "0.5",
            "--pids-limit",
            "32",
            "--ulimit",
            "cpu=2:2",
            "--ulimit",
            "nofile=64:64",
            "--ulimit",
            "fsize=1048576:1048576",
            "--entrypoint",
            "python3",
            IMAGE,
            "-I",
            "-S",
            "-B",
            "-u",
            "-",
        ]
        process = None
        output = bytearray()
        state = "finished"
        try:
            created = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10
            )
            if created.returncode:
                raise RuntimeError("The isolated Python image is unavailable; ask your parent.")
            process = subprocess.Popen(
                [self.docker, "start", "-a", "-i", name],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            process.stdin.write(code.encode())
            process.stdin.close()
            deadline = time.monotonic() + 6
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    if time.monotonic() >= deadline:
                        state = "time_limit"
                        break
                    events = selector.select(timeout=0.1)
                    if not events:
                        continue
                    chunk = process.stdout.read1(4096)
                    if not chunk:
                        break
                    output.extend(chunk)
                    if len(output) > 16384:
                        del output[16384:]
                        state = "output_limit"
                        break
            if state == "finished":
                process.wait(timeout=2)
                if process.returncode:
                    state = "error"
        finally:
            # Exact generated name only. Never prune containers or act on a
            # learner-supplied identifier. Missing --rm containers are normal.
            try:
                # Disconnect the bounded output reader before stopping the
                # container: an output flood can otherwise backpressure the
                # Docker attach stream while removal waits for it to drain.
                if process:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=3)
                    process.stdout.close()
                subprocess.run(
                    [self.docker, "rm", "-f", name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
                remaining = subprocess.run(
                    [
                        self.docker,
                        "ps",
                        "-a",
                        "--filter",
                        "name=^/" + name + "$",
                        "--format",
                        "{{.ID}}",
                    ],
                    capture_output=True,
                    timeout=5,
                )
                if remaining.returncode or remaining.stdout.strip():
                    UNHEALTHY.set()
                    raise RuntimeError("Runner cleanup failed; parent inspection required.")
            except (OSError, subprocess.TimeoutExpired):
                UNHEALTHY.set()
                raise RuntimeError(
                    "Runner cleanup could not be verified; parent inspection required."
                ) from None
            finally:
                if process:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=3)
                    process.stdout.close()
                SLOTS.release()
        return Result(state, output.decode("utf-8", errors="replace"), process.returncode)
