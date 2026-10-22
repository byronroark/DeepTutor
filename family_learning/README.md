# Family Learning fork development

This fork preserves the upstream Apache-2.0 license and notices. Base:
DeepTutor v1.6.15, a31d82624c27d75f4e771d4fcb78dce16470b383. The local engine
now lives in `deeptutor/family_learning`; authenticated routes and a first
parent/learner page are opt-in. See [integration status](INTEGRATION.md).

The prototype was developed alongside `byronroark/omarchy-family-lab` and is
preserved here as a tested starting point for DeepTutor integration. This
folder is the home for subsequent local learning-engine development. Desktop
enrollment, policy and notification integration remain in Omarchy Family Lab;
the escalation and gateway modules here are a development checkpoint, not
separately deployed services.

- `learning/LOCAL_LESSONS.md`: local lesson authority, private writing review,
  progression and integration requirements.
- `../deeptutor/family_learning/starter_lessons.json`: draft Python concept, fractions and writing
  lessons requiring parent review before assignment.
- `learning/TUTOR_GATEWAY.md`: separately billed API allowance prototype,
  disabled pending privacy and content-control readiness.
- `learning/README.md`: desktop-first escalation design; no Discord bot deployed.

No credentials, account databases, learner writing or household runtime data
are included. No live model calls are made by these tests. Python execution,
production deployment and sandbox acceptance remain unfinished; the existing
child installation has not been changed.

Run the five `family_learning/tests/check_*.py` scripts with Python 3. They
cover 48 offline cases. The dedicated workflow runs only these additions;
full upstream application checks are still required when integration begins.

Keep changes in this directory and narrow adapters wherever possible. Bring
upstream updates into a review branch and run regression checks before using
new builds with a learner. Never commit deployment data or secrets.
