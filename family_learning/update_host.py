"""Reviewed app-image update for an existing managed Family Learning host.

Preserves network/origin/provider environment, mounts, accounts and coursework.
Stops writers before backup and retains the previous container for rollback.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.request import urlopen


def run(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def healthy():
    for _ in range(90):
        try:
            with urlopen("http://127.0.0.1:3785/api/auth/status", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(1)
    raise RuntimeError("App startup failed")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--archive", required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--image", required=True)
    a = p.parse_args()
    if os.getuid() != 0:
        raise SystemExit("Run in the private administrator terminal")
    archive = Path(a.archive)
    if archive.is_symlink() or not archive.is_file():
        raise ValueError("Unexpected archive")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", a.image) or not re.fullmatch(
        r"[a-f0-9]{64}", a.sha256
    ):
        raise ValueError("Expected immutable image ID and archive checksum")
    owner = int(os.environ.get("SUDO_UID", "0"))
    for path in [archive, archive.parent]:
        info = path.lstat()
        if path.is_symlink() or info.st_uid not in {0, owner} or info.st_mode & 0o022:
            raise ValueError("Untrusted staging path")
    with archive.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != a.sha256:
            raise ValueError("Checksum mismatch")
    name = "family-learning-learner"
    root = Path("/var/lib/family-learning")
    state = root / "installation.json"
    if state.is_symlink() or state.stat().st_uid != 0 or state.stat().st_mode & 0o022:
        raise ValueError("Unexpected metadata")
    metadata = json.loads(state.read_text())
    old = json.loads(run("docker", "inspect", name))[0]
    if (
        metadata.get("phase") != "ready"
        or old["Config"].get("Labels", {}).get("family-learning.owner") != "learner-host"
    ):
        raise ValueError("Unexpected installation")
    network = json.loads(run("docker", "network", "inspect", name))[0]
    if (
        not network["Internal"]
        or network.get("Labels", {}).get("family-learning.owner") != "learner-host"
        or old["HostConfig"]["PortBindings"]
    ):
        raise ValueError("Unexpected network exposure")
    if sorted(m["Destination"] for m in old["Mounts"]) != ["/app/data", "/run/family-python"]:
        raise ValueError("Unexpected mounts")
    address = old["NetworkSettings"]["Networks"][name]["IPAddress"]
    run("docker", "load", "-i", archive)
    if run("docker", "image", "inspect", a.image, "--format", "{{.Id}}") != a.image:
        raise ValueError("Image identity mismatch")
    env = dict(value.split("=", 1) for value in old["Config"]["Env"] if "=" in value)
    if any(
        env.get(key) != "1"
        for key in ["FAMILY_LEARNING_ENABLED", "FAMILY_LEARNING_LOCAL_ONLY", "FAMILY_LEARNER_HOST"]
    ):
        raise ValueError("Learner restrictions must stay enabled")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    prior = name + "-before-app-update-" + stamp.lower()
    run(
        "systemctl",
        "stop",
        "family-learning-web.service",
        "family-learning-app.service",
        "family-learning-broker.service",
    )
    renamed = disconnected = created = False
    try:
        backup = root / ("before-app-update-" + stamp + ".tar")
        run("tar", "-C", root, "-cpf", backup, "data", "installation.json")
        backup.chmod(0o600)
        run("docker", "rename", name, prior)
        renamed = True
        run("docker", "network", "disconnect", name, prior)
        disconnected = True
        args = [
            "docker",
            "create",
            "--name",
            name,
            "--label",
            "family-learning.owner=learner-host",
            "--network",
            name,
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
        for env in old["Config"]["Env"]:
            args += ["-e", env]
        for mount in old["Mounts"]:
            args += [
                "-v",
                mount["Source"] + ":" + mount["Destination"] + ("" if mount["RW"] else ":ro"),
            ]
        run(*args, a.image)
        created = True
        run(
            "systemctl",
            "start",
            "family-learning-broker.service",
            "family-learning-app.service",
            "family-learning-web.service",
        )
        healthy()
        for service in ["broker", "app", "web"]:
            run("systemctl", "is-active", "--quiet", "family-learning-" + service + ".service")
        metadata.update(image=a.image, app_backup=str(backup), app_previous_container=prior)
        state.write_text(json.dumps(metadata))
        print(
            "VERIFIED: app updated; accounts, coursework, network settings, parent connections and learner restrictions preserved."
        )
    except Exception:
        subprocess.run(
            ["systemctl", "stop", "family-learning-web.service", "family-learning-app.service"]
        )
        if created:
            run("docker", "rm", "-f", name)
        if renamed:
            run("docker", "rename", prior, name)
        if disconnected:
            run("docker", "network", "connect", "--ip", address, name, name)
        run(
            "systemctl",
            "start",
            "family-learning-broker.service",
            "family-learning-app.service",
            "family-learning-web.service",
        )
        raise


if __name__ == "__main__":
    main()
