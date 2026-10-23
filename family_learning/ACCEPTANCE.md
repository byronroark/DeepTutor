# Disposable acceptance and Python runner

All acceptance accounts and writing are synthetic and separate from household
data. The acceptance frontend listens through a localhost-only TCP proxy on
127.0.0.1:3783; its Docker network is internal and has no general Internet
egress. There are no configured models or API keys. The existing household
container stays stopped and unchanged.

The frontend is compiled from fork source. `Dockerfile.acceptance` overlays
the fork backend and compiled standalone frontend onto the pinned upstream
1.6.15 dependency runtime. Supply a context containing only `deeptutor/` and
the compiled standalone bundle as `web/`; never include household data or
credentials. This acceptance artifact is not a complete dependency rebuild.

`tests/check_acceptance_http.py` runs only with `FAMILY_HTTP_LIVE_TEST=1` and
disposable accounts at the fixed loopback URL. It reads the test credential
from a private temporary file, never from a command argument or Git. It covers
real proxy login, feedback/unlocks, writing revisions, revocation and origin
checks. The persistence marker is outside Git and is used to verify progress
after restarting only the disposable test container.

Acceptance was run on 2026-10-22 with synthetic accounts. The real frontend
proxy preserved Origin, valid writes succeeded and a cross-origin write was
rejected. Learner `/api/settings` returned 403 with local-only mode enabled.
An authenticated attempt to open the actual `/ws` AI chat socket was rejected
with HTTP 403 before upgrade. Browser checks covered assignment, prepared
feedback, correct-answer unlock, custom number-exercise authoring, parent-only
answer/hint preview and sign-out. These observations do not replace the
separate household acceptance. The later default-deny route audit, interrupted
runner recovery, and installation/rollback acceptance are recorded in [PILOT.md](PILOT.md).

## Host-side Python primitive

`deeptutor/family_learning/python_runner.py` uses an official Python runtime
pinned by digest. It creates a fresh container per run with UID 65534, no
network, no host mounts, no extra capabilities, no new privileges, read-only
root, private IPC, 8 MB temporary scratch, 128 MB RAM without swap, 0.5 CPU,
32 processes, a CPU limit, six-second wall limit and 16 KB output bound.
Container logs are disabled. It removes the exact generated container after
execution and verifies removal; unverifiable cleanup disables further runs in
the process until parent inspection. At most two programs run concurrently.

The runner accepts a small lesson syntax subset: variables, arithmetic,
conditionals, loops, lists and selected ordinary functions. Imports, attribute
access, definitions, underscore-prefixed names and arbitrary function calls
are rejected. These checks express lesson scope, not the isolation boundary.
Container acceptance deliberately bypasses syntax checks to test network,
read-only filesystem, UID and secret/socket absence independently.

Tests also cover expected loop output, CPU/memory/output exhaustion, scratch
discard and container cleanup. A discovered output-flood cleanup hang was fixed
by disconnecting attach output before removal; the complete rerun passed.

The runner remains HOST-SIDE and is not installed as a household service.
Assigned Python exercises now use a scoped authenticated Unix broker, assignment
epoch checks, parent-owned output expectations, rate limits and server-side
grading. The complete disposable HTTP and browser flows passed; see
`PYTHON_LESSONS.md`. NEVER mount Docker's socket into DeepTutor or expose the
runner directly to a learner. Parent recovery and household acceptance remain.
Containers share the host kernel; these checks are not proof against all
kernel/runtime vulnerabilities. Keep execution disabled in the household until
the complete broker path and recovery behavior pass acceptance.
