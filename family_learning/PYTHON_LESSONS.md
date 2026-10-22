# Assigned Python exercises — acceptance implementation

The learner-facing endpoint is POST
`/api/family-learning/courses/{course}/lessons/{lesson}/python`. It accepts
only program text and a request ID. Identity comes from the existing authenticated
session; the body cannot supply a learner ID, role, command, container settings,
expected output or grading decision. The API checks assignment before delegating.

## Privilege boundary

The backend connects to a private Unix socket using a narrowly scoped token.
Only the host broker invokes Docker. Never mount Docker's socket into DeepTutor.
Mount only the private broker directory read-only, containing its socket and
scoped token, with UID ownership matching the backend. The runner containers
receive neither this directory nor lesson storage, credentials or any host mount.

The host broker reads the same parent-owned lesson database as the backend.
It forces the learner role and checks assignment, course order and exercise
kind itself. Only then may it call the fixed, bounded Python runner. Four
broker requests and two runner containers are permitted concurrently. HTTP
headers/body reads have time and size limits. There is no TCP listener.

Both the host and backend must use reviewed fork code, trusted storage and
correct file permissions. A backend compromise is outside session isolation:
the broker token trusts the backend to identify the signed-in learner, but
still does not grant arbitrary host commands, Docker options or unrestricted
code execution. The broker never accepts a learner-provided execution command.

## Grading and concurrency

Python exercise definitions contain `starter_code`, `expected_output` and
optional syntax requirements (`assignment`, `for_loop`, `while_loop`). Expected
output is omitted from learner views. Output is compared after CRLF normalization
and ignoring trailing newline characters; other whitespace remains significant.
There are no arbitrary parent/learner executable grading scripts in this version.

Syntax requirements check AST presence; they are useful exercise checks, not
proof of understanding or resistance to intentionally trivial solutions.
Future lessons can add controlled input/output test cases and parent review.

The broker records a durable running job, releases the database write lock while
executing, then rechecks assignment and its epoch before saving feedback or
unlocking progress. Revocation followed by re-enrollment during execution still
invalidates the old result. Completed replay IDs return the original result
without another container; changing a replay's payload is refused. A plain
answer submission cannot grade a Python exercise.

Only one active run per learner and ten admissions per minute are allowed.
Runner errors, syntax feedback and resource limits never unlock progress.
Programs and feedback stay in private local storage. Saving a program draft
does not execute it. The UI preserves request IDs after ambiguous transport
failure, disables the editor during execution and renders output as text.

Interrupted broker jobs remain blocked rather than silently rerun. An operator
must inspect active `family-python-*` containers and job records before recovery;
a safe parent recovery interface is still needed before routine deployment.

## Acceptance configuration

In addition to normal Family Learning authentication/origin settings, the backend
requires `FAMILY_PYTHON_ENABLED=1`, `FAMILY_PYTHON_SOCKET` (default
`/run/family-python/broker.sock`) and `FAMILY_PYTHON_TOKEN` (default
`/run/family-python/token`). Missing/disabled service returns an unavailable
message and never falls back to executing code inside the web app.

For the disposable acceptance instance, a host process runs:

```
python3 -m deeptutor.family_learning.python_broker \
  --socket /tmp/family-python-acceptance/broker.sock \
  --token /tmp/family-python-acceptance/token \
  --lessons /tmp/family-learning-acceptance-runtime/data/system/family-learning
```

The private directory must exist with mode 0700. `--initialize-token` explicitly
creates a new mode-0600 credential and refuses to overwrite one. Never print it
or commit it. The accepted application mounts that directory read-only and has
no Docker socket. The host broker is not installed or enabled as a household
service by this PR.

## Verification

Unit checks cover correct/wrong output, syntax requirements, resource failures,
replay, assignment isolation, revocation/re-enrollment during execution, rate
limits, pending jobs and explicit draft saves. Socket tests verify scoped
authentication, schema restrictions and safe error propagation. HTTP tests
verify backend identity binding and refusal of forged learner fields.

With the source-built disposable app, `FAMILY_HTTP_LIVE_TEST=1
FAMILY_PYTHON_HTTP_TEST=1 python3 family_learning/tests/check_acceptance_http.py`
tests the complete frontend proxy → authenticated backend → Unix broker → real
container path. It verifies wrong output/hint, correction, idempotent replay,
unlocking and a passing loop. A real browser walkthrough also passed this
sequence with synthetic accounts. The household installation remains unchanged.

Household deployment still requires parent recovery controls, complete public
route audit, restart/recovery acceptance and review of the installation path.
No AI model is called and no API credit is spent.
