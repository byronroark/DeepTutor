"""Install a fresh, loopback-only learner host. Run as root from reviewed staging.

Never copies parent data. Fresh accounts are created privately before listeners
start. Root-managed code and a non-login service account separate the host
broker from the child's account. Intended for Linux/systemd with Docker installed.
"""

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import socket
import subprocess
import time
from urllib.request import urlopen

ROOT = Path("/var/lib/family-learning")
CODE = Path("/opt/family-learning")
NAME = "family-learning-learner"
ACCOUNT = "familylearn"
MARKER = "# Managed Family Learning learner host\n"


def run(*args, capture=True):
    result = subprocess.run(list(map(str, args)), check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""


def write(path, text, mode=0o600, uid=0, gid=0):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Refusing linked path: " + str(path))
    with path.open("w") as target:
        target.write(text)
    path.chmod(mode)
    os.chown(path, uid, gid)


def checked_source(source):
    source = Path(source).absolute()
    expected = int(os.environ.get("SUDO_UID", os.getuid()))
    for item in [source, *source.rglob("*")]:
        info = item.lstat()
        if item.is_symlink() or info.st_uid not in {0, expected} or info.st_mode & 0o022:
            raise ValueError("Staging must be owned, unlinked, and not writable by others")
    for file in [
        "learner_bootstrap.py",
        "acceptance_proxy.py",
        "deeptutor/family_learning/python_broker.py",
    ]:
        if not (source / file).is_file():
            raise ValueError("Incomplete deployment bundle")
    return source


def account():
    try:
        user = pwd.getpwnam(ACCOUNT)
    except KeyError:
        run("useradd", "--system", "--home-dir", ROOT, "--shell", "/usr/bin/nologin", ACCOUNT)
        user = pwd.getpwnam(ACCOUNT)
    if (
        user.pw_uid in {0, 1000, 1001}
        or user.pw_dir != str(ROOT)
        or not user.pw_shell.endswith("/nologin")
    ):
        raise ValueError("Unexpected existing service account")
    return user


def units(
    image,
    address,
    uid,
    gid,
    runner_image="python@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2",
):
    common = (
        MARKER
        + "[Unit]\nDescription=Family Learning learner host\nRequires=docker.service\nAfter=docker.service\n"
    )
    broker = (
        common
        + f"""\n[Service]
User={ACCOUNT}
Group={ACCOUNT}
SupplementaryGroups=docker
Environment=HOME={ROOT}/broker
WorkingDirectory={CODE}
ExecStart=/usr/bin/python3 -I -B {CODE}/broker_entry.py --socket {ROOT}/broker/broker.sock --token {ROOT}/broker/token --lessons {ROOT}/data/system/family-learning --image {runner_image}
UMask=0077
NoNewPrivileges=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths={ROOT}/data {ROOT}/broker
PrivateTmp=true
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
"""
    )
    app = (
        common
        + f"""Requires=family-learning-broker.service
After=family-learning-broker.service

[Service]
ExecStart=/usr/bin/docker start -a {NAME}
ExecStop=/usr/bin/docker stop -t 30 {NAME}
TimeoutStopSec=45
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    )
    web = (
        MARKER
        + f"""[Unit]
Description=Family Learning loopback browser endpoint
Requires=family-learning-app.service
After=family-learning-app.service

[Service]
User={ACCOUNT}
Group={ACCOUNT}
ExecStart=/usr/bin/python3 -I -B {CODE}/acceptance_proxy.py {address} --port 3785
NoNewPrivileges=true
ProtectHome=true
ProtectSystem=strict
PrivateTmp=true
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
"""
    )
    return {"broker": broker, "app": app, "web": web}


def check_resume(digest):
    for item in [ROOT, ROOT / "installation.json", CODE, *CODE.rglob("*")]:
        info = item.lstat()
        if item.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Resume requires unlinked, root-owned installation metadata and code")
    state = json.loads((ROOT / "installation.json").read_text())
    if state.get("phase") != "preparing" or state.get("archive_sha256") != digest:
        raise ValueError("Resume requires the matching interrupted image archive")
    return state


def install(source, archive, digest, runner_image=None, resume=False, learner_login="learner"):
    if os.getuid() != 0:
        raise ValueError("Run the reviewed installer with sudo in a private terminal")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", learner_login):
        raise ValueError("Use a plain learner login name")
    source = checked_source(source)
    if not isinstance(runner_image, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", runner_image):
        raise ValueError("Expected a pinned offline Python image ID")
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Expected an image archive SHA-256")
    archive = Path(archive).absolute()
    if archive.is_symlink() or archive.parent != source or not archive.is_file():
        raise ValueError("Use the reviewed image archive in the staging directory")
    with archive.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != digest:
        raise ValueError("Image archive checksum mismatch")
    state = ROOT / "installation.json"
    if resume:
        previous = check_resume(digest)
        if previous.get("learner_login", learner_login) != learner_login:
            raise ValueError("Resume must preserve the selected learner login")
        if run("docker", "ps", "-aq", "--filter", "name=^/" + NAME + "$"):
            raise ValueError("Resume stops when a learner container already exists")
        for name in ["broker", "app", "web"]:
            result = subprocess.run(
                ["systemctl", "is-active", "--quiet", "family-learning-" + name + ".service"]
            )
            if result.returncode not in {3, 4}:
                raise ValueError("Resume requires stopped learner services")
    elif ROOT.exists() or CODE.exists():
        raise ValueError(
            "Existing installation found. No data was overwritten; use a reviewed upgrade."
        )
    for name in ["broker", "app", "web"]:
        file = Path("/etc/systemd/system/family-learning-" + name + ".service")
        if file.exists() and (file.is_symlink() or not file.read_text().startswith(MARKER)):
            raise ValueError("Refusing an unrelated service file")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 3785))
    user = account()
    uid, gid = user.pw_uid, user.pw_gid
    ROOT.mkdir(mode=0o700, exist_ok=True)
    ROOT.chmod(0o750)
    os.chown(ROOT, 0, gid)
    write(
        state,
        json.dumps(
            {"phase": "preparing", "archive_sha256": digest, "learner_login": learner_login}
        ),
    )
    if CODE.exists() and not resume:
        raise ValueError(
            "Code directory exists; inspect the interrupted deployment before continuing"
        )
    CODE.mkdir(mode=0o755, exist_ok=resume)
    write(
        CODE / "broker_entry.py",
        "import runpy,sys\nsys.path.insert(0,'/opt/family-learning')\nrunpy.run_module('deeptutor.family_learning.python_broker',run_name='__main__')\n",
        0o644,
    )
    for name in ["learner_bootstrap.py", "acceptance_proxy.py"]:
        shutil.copy2(source / name, CODE / name)
        (CODE / name).chmod(0o644)
    (CODE / "deeptutor").mkdir(mode=0o755, exist_ok=resume)
    write(CODE / "deeptutor/__init__.py", "", 0o644)
    shutil.copytree(
        source / "deeptutor/family_learning",
        CODE / "deeptutor/family_learning",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        dirs_exist_ok=resume,
    )
    for item in (CODE / "deeptutor").rglob("*"):
        item.chmod(0o755 if item.is_dir() else 0o644)
        os.chown(item, 0, 0)
    data = ROOT / "data"
    settings = data / "user/settings"
    settings.mkdir(mode=0o700, parents=True, exist_ok=True)
    for item in [data, data / "user", settings]:
        item.chmod(0o700)
        os.chown(item, uid, gid)
    if not resume:
        write(
            settings / "auth.json",
            json.dumps(
                {"enabled": True, "username": "", "password_hash": "", "cookie_secure": False}
            ),
            uid=uid,
            gid=gid,
        )
        write(
            settings / "model_catalog.json",
            json.dumps({"version": 1, "services": {}}),
            uid=uid,
            gid=gid,
        )
    broker = ROOT / "broker"
    broker.mkdir(mode=0o700, exist_ok=True)
    os.chown(broker, uid, gid)
    if not resume:
        write(broker / "token", secrets.token_urlsafe(48), uid=uid, gid=gid)
    run("systemctl", "start", "docker.service")
    print("Loading the checksum-verified learner image…", flush=True)
    run("docker", "load", "-i", archive)
    if run("docker", "image", "inspect", runner_image, "--format", "{{.Id}}") != runner_image:
        raise ValueError("Offline Python image is unavailable")
    image = run("docker", "image", "inspect", "family-deeptutor:acceptance", "--format", "{{.Id}}")
    if run("docker", "ps", "-aq", "--filter", "name=^/" + NAME + "$"):
        raise ValueError("A learner container already exists; no container was replaced")
    networks = run("docker", "network", "ls", "-q", "--filter", "name=^" + NAME + "$")
    if networks and not resume:
        raise ValueError("A learner network already exists; no network was replaced")
    if not networks:
        run(
            "docker",
            "network",
            "create",
            "--internal",
            "--label",
            "family-learning.owner=learner-host",
            NAME,
        )
    network = json.loads(run("docker", "network", "inspect", NAME))[0]
    if (
        not network.get("Internal")
        or network.get("Labels", {}).get("family-learning.owner") != "learner-host"
        or network.get("Containers")
    ):
        raise ValueError("Expected an unused, internal learner-owned network")
    subnet = ipaddress.ip_network(network["IPAM"]["Config"][0]["Subnet"])
    address = str(subnet.network_address + 2)
    # Bootstrap runs without network access, with no listener and no parent's data.
    print(
        "Create separate application passwords privately. These are not Linux passwords.",
        flush=True,
    )
    run(
        "docker",
        "run",
        "--rm",
        "-it",
        "--network",
        "none",
        "--user",
        f"{uid}:{gid}",
        "-v",
        f"{data}:/app/data",
        "-v",
        f"{CODE}/learner_bootstrap.py:/tmp/bootstrap.py:ro",
        "--entrypoint",
        "python",
        image,
        "/tmp/bootstrap.py",
        "--learner",
        learner_login,
        capture=False,
    )
    run(
        "docker",
        "create",
        "--name",
        NAME,
        "--label",
        "family-learning.owner=learner-host",
        "--network",
        NAME,
        "--ip",
        address,
        "--memory",
        "2g",
        "--cpus",
        "1.5",
        "--pids-limit",
        "512",
        "--security-opt",
        "no-new-privileges:true",
        "--log-opt",
        "max-size=5m",
        "--log-opt",
        "max-file=2",
        "-e",
        f"PUID={uid}",
        "-e",
        f"PGID={gid}",
        "-e",
        "FAMILY_LEARNING_ENABLED=1",
        "-e",
        "FAMILY_LEARNING_LOCAL_ONLY=1",
        "-e",
        "FAMILY_LEARNER_HOST=1",
        "-e",
        "FAMILY_PYTHON_ENABLED=1",
        "-e",
        "FAMILY_LEARNING_ORIGIN=http://localhost:3785",
        "-v",
        f"{data}:/app/data",
        "-v",
        f"{broker}:/run/family-python:ro",
        image,
    )
    for name, content in units(image, address, uid, gid, runner_image).items():
        write("/etc/systemd/system/family-learning-" + name + ".service", content, 0o644)
    write(
        "/usr/share/applications/family-learning.desktop",
        "[Desktop Entry]\nType=Application\nName=Family Learning\nComment=Local courses and coding practice\nExec=xdg-open http://localhost:3785/family-learning\nIcon=applications-education\nTerminal=false\nCategories=Education;\n",
        0o644,
    )
    run("systemctl", "daemon-reload")
    try:
        run(
            "systemctl",
            "enable",
            "--now",
            "family-learning-web.service",
            "family-learning-app.service",
            "family-learning-broker.service",
        )
        for attempt in range(90):
            try:
                with urlopen("http://127.0.0.1:3785/api/auth/status", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError("Learner startup did not pass its health check")
        write(
            state,
            json.dumps(
                {
                    "phase": "ready",
                    "image": image,
                    "address": address,
                    "archive_sha256": digest,
                    "learner_login": learner_login,
                }
            ),
        )
    except Exception:
        run(
            "systemctl",
            "stop",
            "family-learning-web.service",
            "family-learning-app.service",
            "family-learning-broker.service",
        )
        raise
    print("Learner host ready: http://localhost:3785/family-learning")
    print(
        "No AI connection, old account database, or parent secret was copied. The learner has no Docker access."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--runner-image", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--learner-login", required=True)
    args = parser.parse_args()
    install(
        args.source,
        args.archive,
        args.sha256,
        args.runner_image,
        resume=args.resume,
        learner_login=args.learner_login,
    )
