# Local lesson journey — engine implemented, interface pending

The engine makes no network or AI calls and executes no learner code. It
stores course versions, assignments, attempts, drafts and parent reviews in
private SQLite storage. It is not deployed into DeepTutor yet.

Parents publish immutable course versions and assign or revoke each learner.
Each submission rechecks assignment and earlier lesson completion, including
request replays. Number and choice exercises return prepared feedback and
hints; passing unlocks the next lesson. Learner views omit answer keys and
locked exercise material. Idempotent requests prevent duplicate attempts.

Writing supports local drafts, immutable submitted versions, parent feedback,
revision and approval. Earlier submissions survive revisions. Only the owning
parent may review. There is no automatic AI grading, export or upload.

Starter material covers Python variable concepts, fractions and a book report.
Python currently uses prediction questions; code execution is rejected. These
are drafts for parent review, not assignments installed on the child's account.

## Required integration

Construct `Actor` ONLY from an authenticated server session, never a request
body. The engine is not an authentication layer. Parent enrollment must govern
which learner identities a parent can assign. Protect parent mutations against
CSRF. Authorize every learner read and write. Keep course JSON containing
answers out of browser static files; render text without executing HTML.

The parent editor, learner interface, review inbox, progress reports, parent
unlock overrides and Ask Dad/Mom transport still need implementation.

Python requires an independently tested ephemeral runner: no network, host
mounts, credentials or Docker socket; unprivileged user; read-only system;
bounded scratch space, CPU, memory, processes, output and execution time;
cleanup after timeout; trusted parent-owned exercise tests. Syntax validation
is feedback, not isolation. Execution must remain disabled until acceptance
tests verify these boundaries.

Optional parent AI review must explicitly export a separate sanitized copy,
never run automatically when a child submits writing.

## Verification

`python3 -B tests/check_local_lessons.py` tests progression, restart, hints,
private views, assignment revocation, actor boundaries, concurrent replay,
immutable versions and writing review using disposable state. Tests do not
modify household accounts, start DeepTutor or spend API credits.
