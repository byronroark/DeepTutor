# Learner PC deployment

The host serves local courses and isolated Python exercises to learners, and the
full DeepTutor dashboard to authenticated parents. Parent navigation, authoring
and provider settings use DeepTutor's shared layout and controls. Learners remain
restricted to Family Learning. Do not copy a parent deployment's data, OAuth
store, account database or session secret to this PC; each parent signs in to
their own provider connection separately.

An optional transfer path is explicit: generate/review/publish on the parent
installation, choose **Download course for learner PC**, then import/review/publish
and assign it on the learner host. Assignments and learner work remain on that
host. This is file transfer, not automatic synchronization. Different parent
accounts own their own imported courses. Shared ownership and automatic delivery
are separate future work.

## Fresh installation

Build the source image with `build_pilot.py`. Stage these files in a private,
parent-owned directory on the learner PC: `learner_host.py`,
`learner_bootstrap.py`, `acceptance_proxy.py`, an empty `deeptutor/__init__.py`,
and the `deeptutor/family_learning/` source package. Do not include `data/`.
Export the app image and the pinned Python runner image to an image archive.
Record its SHA-256 and the runner's immutable image ID.

Review the installer, then run privately on the learner PC:

```sh
sudo python3 learner_host.py --source /absolute/staging/path \
  --archive /absolute/staging/path/images.tar --sha256 ARCHIVE_SHA256 \
  --runner-image sha256:PINNED_PYTHON_IMAGE_ID --learner-login LEARNER_LOGIN
```

The installer verifies ownership, checksums and existing service names before
installing. It creates a dedicated non-login `familylearn` account and fresh
application passwords through a private terminal. Create the first parent
account before the learner; optionally create a second parent account. No password is
accepted through command arguments or chat. Existing/partial data are not
silently replaced; this is a fresh installer, not an upgrade or recovery tool.
An interrupted installation requires inspection before continuing.

The app runs with a 2 GB memory / 1.5 CPU limit on an internal Docker network,
without a Docker socket. Only the immutable host broker receives Docker access;
it runs isolated Python from root-owned code with Python user-site imports
disabled. The child remains outside wheel and docker groups. App data and broker
credentials belong to the separate service UID, not the desktop learner UID.

Services: `family-learning-app`, `family-learning-broker`, `family-learning-web`.
Private state: `/var/lib/family-learning/`; immutable host code:
`/opt/family-learning/`. A **Family Learning** application launcher opens
`http://localhost:3785/family-learning`. Services start at boot and resume with
the PC; existing break/bedtime controls continue governing desktop use.

## Parent access on the home network

Optional direct LAN access uses the reviewed proxy's `--lan-address` argument
with an explicit private IPv4 address. It retains the loopback listener; it does
not bind all interfaces. Allow TCP 3785 in the host firewall only on the LAN
interface, from the household subnet, to that address. Keep authentication and
the learner firewall enabled. Configure `FAMILY_LEARNING_ORIGIN` with an exact
comma-separated list of browser origins, such as
`http://localhost:3785,http://127.0.0.1:3785,http://192.168.50.10:3785`.
Other origins remain rejected for Family Learning mutations. Direct HTTP access
is intended for the trusted home network; do not forward it through the router.
Reserve the host's address in DHCP so the listener and rule remain valid.

By default, the browser listener binds only to `127.0.0.1:3785`. A parent uses an encrypted
SSH local forward to manage the learner host. No router port forwarding or
public/LAN HTTP listener is installed. With the existing administrator SSH alias:

```sh
ssh -F ~/.config/family-help/ssh.conf -o ClearAllForwardings=no \
  -o ExitOnForwardFailure=yes -N -L 127.0.0.1:3785:127.0.0.1:3785 family-help-admin
```

Keep that connection open, then visit `http://localhost:3785/family-learning`.
Use `localhost` for this learner endpoint and `127.0.0.1:3784` for the parent
authoring pilot: separate hostnames keep their independent login cookies apart.
Both endpoints require their own application account. Future parent enrollment
should provide a forwarding-only SSH credential and a one-click launcher; do
not copy an administrator private key to another household member's computer.
An optional second parent application account alone does not configure SSH access
or install the authoring application on that parent's PC.

When the PC hibernates, the site becomes unavailable and the tunnel may close.
Reconnect after waking it. There is no background sync or offline queue yet.

## Boundaries and verification

`FAMILY_LEARNER_HOST=1` blocks model/provider/OAuth/authoring endpoints for
learners. Authenticated parents can use the full dashboard; only learner
accounts are redirected to Family Learning. A fresh installation has an
internal network without Internet egress. The reviewed parent upgrade below
adds an OpenAI-only proxy. Root-managed services, physical
security and the parent's OS administrator account remain trusted boundaries.

The fresh-image acceptance uses synthetic accounts and disposable Docker state:

```sh
FAMILY_LEARNER_IMAGE_TEST=1 python3 family_learning/tests/smoke_learner_image.py
```

It also launches the actual mounted account-bootstrap file from `/tmp`, as the
installer does. That file explicitly imports packages from the image's `/app`
directory; testing only `python -c` would miss this startup-path requirement.

It verifies a remapped service UID, parent import/export, no implicit assignment,
learner rejection of exports, AI endpoint denial, internal networking and absent
published ports / Docker socket. Unit checks cover installer refusal boundaries,
HTTP ownership and the learner-host firewall. A real installation additionally
needs a learner sign-in, isolated Python run and parent import/assignment check.
Back up private learner state while services are stopped before future upgrades;
never replace it with the parent's data directory.

An installation interrupted before container creation may be retried with
`--resume` and the same source/archive arguments after reviewing the failure.
Resume requires a matching checksum in root-owned `preparing` metadata,
root-owned unlinked code, stopped learner services, no learner container, and an
unused internal network bearing the installer ownership label. It preserves
existing account settings, model settings, learning data and the broker token.
It refuses a completed installation or a later-stage partial deployment; those
need a separately reviewed recovery rather than deletion of private data.

## Upgrade an existing course-only portal

Stage `parent_host_upgrade.py`, `parent_https_proxy.py`, and a checksum-recorded
application image archive in a private parent-owned directory. Build the image
from the updated frontend and backend first, then run privately:

```sh
sudo python3 parent_host_upgrade.py --source /absolute/staging/path \
  --archive /absolute/staging/path/parent-host.tar --sha256 ARCHIVE_SHA256 \
  --image sha256:APPLICATION_IMAGE_ID
```

This is a one-time upgrade from a completed course-only installation. It stops
the services before backing up coursework and account state, retains the old
container, and restores that container if startup fails. The browser endpoint
stays on loopback. The app has no Docker socket and the Python runner continues
without networking. A separate root-managed HTTPS proxy accepts only the app's
bridge address and exact OpenAI destinations; its firewall rule is scoped to
that bridge, source, destination and port. Other AI providers require a reviewed
network configuration; enabling the parent dashboard does not enable them.

Provider connections are initially unconfigured. Parents must authorize their
own account; an existing connection on a different PC is not copied. Remote
OAuth may require the manual callback-address flow in Providers until a
dedicated callback tunnel is configured. Keep callback addresses private.

## Preserve deployment changes and update the app

Build a data-free application archive from the reviewed commit. Stage the archive
in a private administrator-owned directory and record its SHA-256 and immutable
Docker image ID. For an existing managed installation:

```sh
sudo python3 update_host.py --archive /absolute/staging/path/app-image.tar \
  --sha256 ARCHIVE_SHA256 --image sha256:APPLICATION_IMAGE_ID
```

The updater preserves the current container environment (including configured
LAN origins and parent HTTPS proxy), data/broker mounts, resource limits and
loopback/LAN listener services. It checks the managed container and internal
network, stops the app and broker before backing up private state, and keeps the
old container for automatic startup rollback. It does not grant learner Docker
access, change an account, perform a retake or purge private backups. The backup
and rollback-container identities are recorded in `installation.json`.

This command updates the application image only. If a change also affects the
host-side Python broker package, review and deploy the matching root-owned
`/opt/family-learning/deeptutor/family_learning/` sources while the broker is
stopped; back up the prior package and restart it with the application. Never
combine new grading/database behavior with an older host broker. Fresh installs
already stage this matching package through `learner_host.py`. Parent policy,
Dino guard and hibernation programs belong to omarchy-family-lab and are not
changed by this application updater.

For an initial direct LAN setup, stage the reviewed `acceptance_proxy.py` at
`/opt/family-learning/acceptance_proxy.py`, append `--lan-address LAN_IP` to the
web service's existing ExecStart, and configure the exact permitted origins in
the app container as described above. On an active UFW host, the firewall rule
has this shape (replace all placeholders after reviewing the interface/subnet):

```sh
sudo ufw allow in on LAN_INTERFACE proto tcp from HOME_SUBNET to LAN_IP port 3785
```

Back up the existing service, proxy, container configuration and data first.
Reload systemd, restart the web service and verify authentication and mutations
from both localhost and the LAN origin. These are reviewed administrator steps,
not automatic changes made by visiting the browser page. The newer Family
Manager enrollment can add an exact parent-source rule once this host prerequisite
is in place; see omarchy-family-lab's `docs/PARENT_TUTOR_ENROLLMENT.md`.

Do not commit deployed account data, OAuth stores, model keys, cookie secrets,
private profiles, image archives, query history, database backups, private SSH
keys or copied installation transcripts. Keep those in private storage outside
the checkout. The source, tests and generic deployment instructions are sufficient
to reproduce the implementation without publishing household state.
