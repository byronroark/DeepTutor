# Family Learning integration checkpoint

The local engine is now packaged under `deeptutor/family_learning/` so it is
included in application builds. Its routes are mounted at `/api/family-learning`;
the new page is `/family-learning`. No AI or Python execution endpoint is added.

## Development enablement

Routes are disabled by default. A controlled development deployment needs:

- DeepTutor authentication enabled and a normal signed-in account. Auth-disabled
  mode is rejected rather than treated as a parent.
- `FAMILY_LEARNING_ENABLED=1` on the backend.
- `FAMILY_LEARNING_ORIGIN` set to the exact browser origin, for example
  `http://127.0.0.1:3782`, with no path. Missing configuration fails closed for
  writes. The frontend proxy must preserve the browser's Origin header.

The parent role currently requires an existing DeepTutor administrator account.
Guardian-only accounts are not enrolled into course ownership yet. Only accounts
with the learner preset appear in assignment choices. Identity and role are
derived from DeepTutor's authenticated token; body fields cannot select them.
Assignments and every learner operation are checked by the engine. A second
administrator cannot read another administrator's courses or writing submissions.

SQLite data lives at `data/system/family-learning`, not in the learner workspace
or any code runner. It contains local private writing and must be backed up and
protected like account data. No export to AI is implemented.

## Implemented screens

Parents can add starter material, create a single-exercise course, inspect the
lesson text, assign/revoke it, see exercise state and attempts, read submissions,
request revisions and approve writing. Publishing identical material is
idempotent. Published course versions are immutable; editing existing courses
and multi-step authoring remain future work.

Learners see assigned courses, prepared feedback, retries, sequential unlocks,
writing draft saves, submission state and parent feedback. Saving is explicit;
autosave and unsaved-change navigation warnings remain future work.

The route is currently reached directly, with no sidebar/default-home changes.
The live household installation has not been enabled or replaced. Do not claim
the new page disables existing DeepTutor chat routes: a learner-only deployment
still needs explicit server-side removal of unrestricted AI surfaces.

## Validation and remaining acceptance

Engine and HTTP route tests cover local progression, identity isolation,
revocation, replay, CSRF origin refusal, anonymous/auth-disabled refusal and the
writing draft → submit → revise → approve workflow. Rendered UI tests cover
learner progression, parent review and sign-in failures. Tests use fake identities
and disposable records, not production accounts.

Full source-built container, real login/proxy behavior, persistence across a
container restart, browser visual acceptance, custom lesson authoring and live
household acceptance remain required before deployment. The first interface is
English; the existing i18n lint warns on untranslated copy. Python sandbox,
Ask Dad/Mom connections, parent unlock overrides and complete report exports
remain unimplemented. No live model calls or API spending were introduced.
