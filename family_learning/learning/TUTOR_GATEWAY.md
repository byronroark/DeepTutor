# Family Tutor spending gateway — staged, not live

The parent ChatGPT connection prepares lessons using the parent's subscription.
It remains bound to that parent inside DeepTutor. The learner does not receive
the parent's login or subscription credentials. Interactive learner tutoring
uses a separate OpenAI project and separately billed API key.

## Current implementation

`weekly_budget.py` reserves a conservative maximum charge before each upstream
request. The allowance is $5, resets Monday at midnight America/New_York, and
does not roll over. SQLite transactions prevent concurrent requests from
overbooking the allowance. Restarting the gateway preserves reservations.
Only verified provider usage releases unused reservations; failed, interrupted
or ambiguous requests keep the full reservation. An unexpected usage-bound
violation stops further admissions pending parent investigation.

`luna_gateway.py` accepts only text Chat Completions for `gpt-6-luna`, with one
answer, at most 1,024 completion tokens, no reasoning, no stored responses and
the standard service tier. It refuses hosted paid tools, images and audio.
Function definitions are included in the input reservation. Rates reviewed
2026-10-21: $0.10 per million input tokens and $0.50 per million output tokens.
Cached-token discounts are not assumed. The gateway stops after 2026-11-20
until its pricing is reviewed in code. No automatic upstream retries occur.

The key stays in a private host file outside the repository and container.
DeepTutor receives a separate local bearer token. Only its fixed internal
address 172.30.60.2 may use this deployment's gateway at 172.30.60.1:11435.
These addresses match the existing isolated deployment; enrollment of other
households still needs parameterized network configuration.

The same listener allows end-to-end TLS CONNECT only to `auth.openai.com:443`
and `chatgpt.com:443` for the parent's Codex sign-in. Resolved private addresses
are refused. `api.openai.com` is deliberately not a tunnel destination; API
traffic must pass the allowance checks. This is not a general Internet proxy.

## Installation and secrets

Run `python3 learning/setup_gateway.py` as the desktop parent. It stages private
runtime files and a stopped user service, preserving the local bearer token.
It does not change DeepTutor, start Docker, enable the schedule or enable child
traffic. With `--enter-api-key`, it prompts in a private terminal without echo.
Never put a key in chat, command arguments, Git, or a screenshot. Re-running
the installer does not rotate the bearer token. A changed existing service is
backed up privately before replacement.

Keep an independently configured project spending limit and prepaid credit
with automatic recharge off as backstops. Provider enforcement can lag. This
gateway controls only requests routed through it, not other holders of the key
or unrelated project spending. Do not reuse the dedicated key elsewhere.

## Live activation is blocked

The learner is nine. OpenAI's under-18 guidance requires Zero Data Retention
before processing personal data of children under 13. `store:false` is not
Zero Data Retention. No production `child-api-ready` marker has been created.
An API key or a successful payment must never create that marker implicitly.

Parent-reviewed course authorization on every learner turn, evaluated content
boundaries, the privacy arrangement, and authenticated DeepTutor integration
must pass before child activation. The developer prompt is an additional
instruction, not a proven content filter or course authorization layer.

The parent OAuth connection, API project key, Docker proxy environment, model
catalog/grants and live allowance verification still need deployment tests.
No paid requests have been made by these tests. The normal tutor schedule and
child LAN access remain off. Discord transport also remains undeployed pending
access to the always-on edge server.

## Offline verification

- `python3 tests/check_weekly_budget.py`: reservations, concurrency, restart,
  Eastern week/DST boundaries, ambiguous usage and clock rollback.
- `python3 tests/check_luna_gateway.py`: request restrictions, privacy gate,
  source/token checks, admission before upstream, usage reconciliation,
  interrupted streams and CONNECT destination/private-address refusal.

Tests use temporary credentials and disposable ledgers with a mocked provider.
They do not contact OpenAI or enable the installed learner.

Sources: [model pricing](https://developers.openai.com/api/docs/models/gpt-6-luna),
[spend limits](https://developers.openai.com/api/docs/guides/spend-limits),
[under-18 guidance](https://developers.openai.com/api/docs/guides/safety-checks/under-18-api-guidance).
