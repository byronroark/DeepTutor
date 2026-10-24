"""Reviewed root upgrade: full parent dashboard, restricted local learner.

Preserves accounts and coursework. Retains the old container and a stopped-data
backup; restores the old container automatically if startup checks fail.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import time
from urllib.request import urlopen

NAME = "family-learning-learner"
ROOT = Path("/var/lib/family-learning")
CODE = Path("/opt/family-learning")
UNIT = Path("/etc/systemd/system/family-learning-parent-cloud.service")
MARKER = "# Managed Family Learning learner host\n"


def run(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def health():
    for _ in range(90):
        try:
            with urlopen("http://127.0.0.1:3785/api/auth/status", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(1)
    raise RuntimeError("Parent host did not pass startup checks")


def upgrade(source, archive, digest, image):
    if os.getuid() != 0:
        raise ValueError("Run with sudo in the private installation terminal")
    source, archive = Path(source).absolute(), Path(archive).absolute()
    for path in [source, archive, source / "parent_https_proxy.py"]:
        info = path.lstat()
        if (
            path.is_symlink()
            or info.st_uid not in {0, int(os.environ.get("SUDO_UID", "0"))}
            or info.st_mode & 0o022
        ):
            raise ValueError("Untrusted staging path")
    if archive.parent != source:
        raise ValueError("Use the reviewed staged archive")
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError("Image checksum mismatch")
    state = ROOT / "installation.json"
    if state.is_symlink() or state.stat().st_uid != 0:
        raise ValueError("Untrusted installation metadata")
    metadata = json.loads(state.read_text())
    if metadata.get("phase") != "ready" or metadata.get("parent_dashboard"):
        raise ValueError("Expected an existing course-only installation")
    old = json.loads(run("docker", "inspect", NAME))[0]
    if old["Config"].get("Labels", {}).get("family-learning.owner") != "learner-host":
        raise ValueError("Unexpected learner container")
    network = json.loads(run("docker", "network", "inspect", NAME))[0]
    if (
        not network["Internal"]
        or network.get("Labels", {}).get("family-learning.owner") != "learner-host"
    ):
        raise ValueError("Expected the isolated learner network")
    address = old["NetworkSettings"]["Networks"][NAME]["IPAddress"]
    gateway = network["IPAM"]["Config"][0]["Gateway"]
    bridge = "br-" + network["Id"][:12]
    if UNIT.exists():
        raise ValueError("Parent cloud service already exists; review before upgrading")
    target = CODE / "parent_https_proxy.py"
    if target.exists():
        raise ValueError("Parent proxy code already exists; review before upgrading")
    run("docker", "load", "-i", archive)
    if run("docker", "image", "inspect", image, "--format", "{{.Id}}") != image:
        raise ValueError("Expected immutable application image")
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = ROOT / ("before-parent-dashboard-" + timestamp + ".tar")
    previous = NAME + "-before-parent-" + timestamp.lower()
    run(
        "systemctl",
        "stop",
        "family-learning-web.service",
        "family-learning-app.service",
        "family-learning-broker.service",
    )
    renamed = False
    disconnected = False
    created = False
    firewall = False
    try:
        run("tar", "-C", ROOT, "-cpf", backup, "data", "installation.json")
        backup.chmod(0o600)
        shutil.copyfile(source / "parent_https_proxy.py", target)
        target.chmod(0o644)
        os.chown(target, 0, 0)
        UNIT.write_text(
            MARKER
            + f"""[Unit]
Description=Family Learning parent OpenAI-only HTTPS connection
After=docker.service
Requires=docker.service
[Service]
User=familylearn
Group=familylearn
ExecStart=/usr/bin/python3 -I -B {target} --bind {gateway} --peer {address} --port 3786
NoNewPrivileges=true
ProtectHome=true
ProtectSystem=strict
PrivateTmp=true
Restart=on-failure
[Install]
WantedBy=multi-user.target
"""
        )
        UNIT.chmod(0o644)
        run(
            "ufw",
            "allow",
            "in",
            "on",
            bridge,
            "proto",
            "tcp",
            "from",
            address,
            "to",
            gateway,
            "port",
            "3786",
            "comment",
            "Family Learning parent OpenAI proxy",
        )
        firewall = True
        run("docker", "rename", NAME, previous)
        renamed = True
        run("docker", "network", "disconnect", NAME, previous)
        disconnected = True
        user = pwd.getpwnam("familylearn")
        args = [
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
        ]
        for env in [
            f"PUID={user.pw_uid}",
            f"PGID={user.pw_gid}",
            "FAMILY_LEARNING_ENABLED=1",
            "FAMILY_LEARNING_LOCAL_ONLY=1",
            "FAMILY_LEARNER_HOST=1",
            "FAMILY_PYTHON_ENABLED=1",
            "FAMILY_PARENT_CLOUD=1",
            "FAMILY_LEARNING_ORIGIN=http://localhost:3785",
            f"HTTPS_PROXY=http://{gateway}:3786",
            f"HTTP_PROXY=http://{gateway}:3786",
            "NO_PROXY=localhost,127.0.0.1,::1",
        ]:
            args += ["-e", env]
        args += [
            "-v",
            f"{ROOT}/data:/app/data",
            "-v",
            f"{ROOT}/broker:/run/family-python:ro",
            image,
        ]
        run(*args)
        created = True
        run("systemctl", "daemon-reload")
        run("systemctl", "enable", "--now", UNIT.name)
        run(
            "systemctl",
            "start",
            "family-learning-broker.service",
            "family-learning-app.service",
            "family-learning-web.service",
        )
        health()
        for service in ["broker", "app", "web", "parent-cloud"]:
            run("systemctl", "is-active", "--quiet", "family-learning-" + service + ".service")
        details = json.loads(run("docker", "inspect", NAME))[0]
        assert not details["HostConfig"]["PortBindings"]
        assert not any(m["Destination"] == "/var/run/docker.sock" for m in details["Mounts"])
        metadata.update(
            image=image,
            parent_dashboard=True,
            parent_cloud="OpenAI-only",
            previous_container=previous,
            backup=str(backup),
        )
        state.write_text(json.dumps(metadata))
        print(
            "VERIFIED: parent DeepTutor dashboard deployed; learner restriction retained; accounts and coursework preserved."
        )
        print(
            "Parent AI connections require a separate private sign-in; no credentials were copied."
        )
    except Exception:
        subprocess.run(
            [
                "systemctl",
                "stop",
                "family-learning-web.service",
                "family-learning-app.service",
                UNIT.name,
            ]
        )
        if created:
            run("docker", "rm", "-f", NAME)
        if renamed:
            run("docker", "rename", previous, NAME)
        if disconnected:
            run("docker", "network", "connect", "--ip", address, NAME, NAME)
        if firewall:
            run(
                "ufw",
                "delete",
                "allow",
                "in",
                "on",
                bridge,
                "proto",
                "tcp",
                "from",
                address,
                "to",
                gateway,
                "port",
                "3786",
            )
        if UNIT.exists():
            subprocess.run(["systemctl", "disable", UNIT.name])
            UNIT.unlink()
        target.unlink(missing_ok=True)
        run("systemctl", "daemon-reload")
        run(
            "systemctl",
            "start",
            "family-learning-broker.service",
            "family-learning-app.service",
            "family-learning-web.service",
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["source", "archive", "sha256", "image"]:
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    upgrade(args.source, args.archive, args.sha256, args.image)
