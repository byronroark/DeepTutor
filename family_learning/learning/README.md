# Parent-reviewed learning and Discord escalation

## Current status

Development only. `escalation.py` is a tested, durable notification outbox; it
does not connect to Discord, approve requests, run commands, or gate DeepTutor
yet. Do not describe this as deployed or as a content filter.

The separate [tutoring gateway](TUTOR_GATEWAY.md) now has offline-tested weekly
spending controls and a private setup tool. It is staged only; the learner API
and Discord delivery are not enabled.

## Agreed behavior

- Keep the native Omarchy Ask Dad/Mom card first.
- Ping the requesting parent's enrolled Discord identity only after three
  minutes unanswered, or earlier after authenticated desktop heartbeats show
  the helper unreachable. Current detection uses a 60-second heartbeat grace;
  unknown availability waits the full three minutes.
- Learn-topic, existing scoped install, and break-change requests use the same
  authoritative decision in both interfaces. A desktop response stops Discord
  escalation; a Discord response closes the desktop card.
- Use the family's existing Discord server with a parent-only channel. The
  nine-year-old learner needs no Discord account. Send the minimal request
  summary, not browsing history, whole conversations, screenshots, or API keys.
- The bot and request broker must run on the separate always-on edge server.
  A bot on Dad's powered-off PC cannot provide an offline fallback. The tutor
  itself runs on Dad's PC, weekdays 10:00–17:00 America/New_York.

## Required transport boundaries

Use Discord's outbound Gateway for buttons/modal interactions; no public home
HTTP endpoint or router port forwarding. Bind decisions to exact enrolled
server ID, channel ID, parent user ID, backend request ID, reviewed digest and
expiry. Reject everyone else, including server members with unrelated roles.
Disable broad mentions and never interpret message text as a shell command.
Keep the bot token in a private file; never post it in chat or Git.

Discord is an adapter, not a new administrator. Install buttons must call the
existing forced SSH scoped approval endpoint and preserve its current plan,
scope, digest, expiry and one-shot checks. Break buttons call the enrolled
policy endpoint and preserve its episode/revision checks. The edge relay must
hold no general parentadmin SSH key, sudo credential or Docker socket.

Re-fetch pending status immediately before a Discord notification and before
every decision. Record only backend-confirmed decisions. Posting a card and
recording delivery cannot be one distributed transaction: use a stable Discord
message nonce with deduplication, then reconcile stale/duplicate cards on
restart. A racing desktop decision may require removing/disabling a just-sent
card. Do not claim the local outbox alone guarantees exactly-once delivery.

## Learning feature still required

Create a separate learning decision service: topic proposal → parent approve,
deny or suggest an alternative → learner accepts the approved course scope.
Store parent-authored/reviewed lesson material and quizzes separately from
learner answers. Check current course authorization on EVERY turn, including
reconnect/retry and direct API calls. Bind learner identity server-side;
never trust a learner-supplied user ID or topic title as authorization.

A topic approval does not make arbitrary free chat safe. Use assigned lesson
flows and evaluate output/subject boundaries. Prompt instructions and local
models are not reliable substitutes for a content enforcement layer. The
upstream learner preset currently exposes chat/reading, not unrestricted
Mastery Path. Do not broaden the child's account to bypass that restriction.

## Tests

`python3 tests/check_escalation.py` exercises timing, heartbeat recovery,
restarts, immutable snapshots, delivery leases, concurrent senders, queued
installs and decisions arriving through another parent/interface. All tests
use disposable state and no external service.
