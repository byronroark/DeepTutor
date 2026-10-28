# Parent-reviewed learning topics

Learners can submit a short subject from **Family Learning → Ask Dad about a
learning topic**. Only enrolled learner accounts can submit. Each learner sees
their own requests; parent administrators can review them, replace the subject,
approve it or decline it. At most three requests may await review, with a minute
between new requests while an earlier one is still pending. IDs are idempotent
and decisions require the original topic
snapshot and a still-pending request. Replaying a decision fails.

The separate private `topic-requests.sqlite3` database lives beside the lesson
database under `data/system/family-learning`. Existing courses, progress,
attempts and provider credentials are unchanged. Topic text and statuses stay
local unless the household explicitly enrolls the separate Discord adapter.

Approval records a learning idea. It does **not** invoke a model, generate a
draft, publish or assign a course, unlock any website, or change a lesson's
scope. A parent separately uses the approved subject with **Create course with
AI**, reviews the generated material and explicitly assigns the course.
Do not include personal details in a topic.

## Optional Family Lab relay

The companion Family Lab repository supplies a native themed parent watcher
and a Discord adapter. Normal browser review requires the existing signed-in
parent session, configured Origin and JSON CSRF checks. The optional relay
instead uses separately enrolled forced SSH accounts and a root-reviewed
topic-only wrapper. It runs `topic_requests_cli` as the managed app's service
UID inside the existing container. The edge receives no administrator SSH key,
application password, provider credentials or Docker socket.

The CLI is an internal trusted-transport entry point, not a general remote
parent login. Do not expose it through a shell, a generic Docker executor, or
an unauthenticated HTTP route. The wrapper must accept only `topic-pending`
and bounded `topic-decision` objects, bind parent identity to the enrolled
route, and invoke this exact module without caller-controlled code or paths.
Discord decisions must also match the enrolled server, channel, parent user,
source request and displayed topic. Editing approves a replacement subject;
it does not edit another request or silently prepare educational content.

Source rows remain authoritative: a desktop/browser decision invalidates a
Discord decision. A lost connection means unconfirmed, not approved. Learners
can refresh to see the source status.

## Verification

`tests/test_family_topic_requests.py` checks isolation, parent-only decisions,
edits, request limits and replay rejection using temporary data. The existing
HTTP router applies its session and Origin checks to the new routes. Live
deployment additionally needs native popup and Discord approve/deny/edit
acceptance, confirmation that a parent browser response wins, and a check that
neither an AI request nor an assignment occurs merely by approving an idea.
