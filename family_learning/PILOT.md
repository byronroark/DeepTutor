# Parent-only local pilot

This pilot is separate from the household installation. It listens only on
127.0.0.1:3784, uses an internal Docker network with no Internet egress, copies
the stopped source data into a private directory, preserves account passwords,
and rotates the copy's session secret. It clears the copied model catalog.
No service is enabled at boot. No child machine or original data is edited.
Learners use only assigned local lessons; parents retain the normal dashboard.
By default, no AI service is configured by the pilot installer.

## Optional parent OpenAI connection

Add `--parent-cloud` to the install command to allow parents to connect their
own OpenAI account from Settings → Providers. Learners remain confined to
assigned local lessons; they cannot start OAuth or access model routes.
This option preserves the internal Docker network and adds a host HTTPS CONNECT
proxy restricted to `auth.openai.com`, `chatgpt.com`, and `api.openai.com`, port
443. Only the pilot container may connect. Private destination addresses and
other hosts are refused. TLS remains end to end; the proxy does not log payloads.

If the host firewall blocks container-to-host traffic, allow only the pilot's
container IP to its bridge gateway on TCP port 3786, on that bridge interface.
Do not open this port to the LAN or allow general container Internet access.

The installer also reserves localhost ports 1455 and 1457 for automatic browser
callback forwarding. Existing listeners cause startup to fail rather than being
replaced. Complete a fresh sign-in in the parent browser; never share callback
addresses or codes. The upstream handler still checks secret state and PKCE.
Only GET requests to its exact callback route bypass the pilot login boundary
when this option is enabled; other settings routes still require parent access.

Reinstall with `--no-parent-cloud` to stop the proxy and callback forwarding.
This preserves lessons and existing private provider credentials. Stop the pilot
or disable this option if another local OAuth client needs the callback ports.
No service is enabled at boot.

Prerequisites: Linux desktop user with Docker access, systemd user services,
Python 3.11+, Node/npm, and a working Docker installation. Docker access is
administrator-equivalent: enroll the parent only, never the child. Review the
source and pinned images before installation. The image overlays the fork onto
the pinned upstream dependency runtime; it is not a fresh dependency rebuild.

From the repository root, install locked frontend dependencies and build:

```sh
npm ci --ignore-scripts --prefix web
python3 family_learning/build_pilot.py
docker pull python@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2
```

Stop the existing tutor before copying its data, then run as the parent without sudo:

```sh
python3 family_learning/pilot.py install --source-data /absolute/path/to/stopped-tutor/data
```

Sign in at http://127.0.0.1:3784/family-learning using the existing parent
account. Publish a starter or a custom exercise, assign it to a learner, and
use the learner's separate login to try it on this PC. Parent pages show
answer keys; learner pages omit them. This listener is deliberately unavailable
to the child's PC. LAN deployment and the weekday operating schedule require a
separate household acceptance step.

Repeating `install` stops only the managed pilot, snapshots its current data
and release, pins the selected local image by ID, updates services, and starts
the new version. It refuses unrelated containers, networks or service files,
occupied ports, linked source files, and source data mounted by a running
container. A failed upgrade attempts to restore the previous snapshot.

```sh
python3 family_learning/pilot.py stop
python3 family_learning/pilot.py start
python3 family_learning/pilot.py rollback
```

Rollback restores the last pre-upgrade data and image, preserving newer data in
`preserved-before-rollback-*`. Before the first upgrade, rollback simply stops
the pilot. Private backups remain under `~/.local/share/family-learning-pilot`;
they contain account hashes and learning work. Never commit or share them.
Only one host Python broker is supported at a time.

## Recovery and acceptance

The broker holds an exclusive host lock. On restart it removes only containers
with the runner's dedicated label, verifies cleanup, and marks unfinished jobs
interrupted. It never reruns a program or awards a grade automatically. The
learner can explicitly run a new attempt. Cleanup failure keeps execution off.

On 2026-10-22, a disposable pilot passed install, repeated install, service
restart, broker SIGKILL recovery, labelled orphan cleanup, upgrade snapshot,
and data-preserving rollback. Authenticated HTTP checks passed after rollback:
prepared feedback, unlocks, writing review, revocation, cross-origin rejection,
real isolated Python execution, and denied settings/files/registration/model
endpoints. Unit tests cover the default-deny boundary including public routes
and WebSockets. Frontend build, type checks, lesson UI tests, Python checks,
formatting and import contracts passed. Household learner acceptance remains
separate; these checks do not guarantee arbitrary educational content is safe.
