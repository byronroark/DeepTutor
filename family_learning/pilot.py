"""Install/start/stop/rollback a private localhost pilot; no changes to the original tutor.

Run as the desktop parent, without sudo. Requires a reviewed local image and
stopped source data. No services are enabled at boot, and no LAN ports opened.
"""

import argparse
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


def run(*args, check=True):
    result = subprocess.run(args, check=check, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def quote(value):
    value = str(value)
    if "\n" in value or "\r" in value:
        raise ValueError("Invalid unit path")
    return (
        '"'
        + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
        + '"'
    )


class Pilot:
    def __init__(self, root, name, port):
        self.root = Path(root).expanduser().absolute()
        if (
            not re.fullmatch(r"family-learning-pilot(?:-[a-z0-9-]+)?", name)
            or not 1024 <= port <= 65535
        ):
            raise ValueError("Invalid pilot name or local port")
        self.name, self.port = name, port
        if self.root.is_symlink():
            raise ValueError("Pilot root cannot be a link")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.stat().st_uid != os.getuid() or self.root.stat().st_mode & 0o077:
            raise ValueError("Pilot root must be private and owned")
        self.units = Path.home() / ".config/systemd/user"
        self.services = [
            name + "-proxy.service",
            name + "-app.service",
            name + "-broker.service",
            name + "-parent-cloud.service",
            name + "-callback.service",
        ]
        self.label = "org.family-learning.pilot=" + str(self.root)

    def state(self):
        return json.loads((self.root / "state.json").read_text())

    def stop(self):
        for service in self.services:
            target = self.units / service
            if target.exists() and "Managed Family Learning local pilot" not in target.read_text():
                raise ValueError("Refusing an unrelated user service")
            run("systemctl", "--user", "stop", service, check=False)

    def remove_container(self):
        info = run("docker", "inspect", self.name, check=False)
        if info:
            labels = json.loads(info)[0]["Config"].get("Labels") or {}
            if labels.get("org.family-learning.pilot") != str(self.root):
                raise ValueError("Refusing an unrelated container")
            run("docker", "rm", "-f", self.name)

    def apply(self, state):
        self.remove_container()
        network = run("docker", "network", "inspect", self.name, check=False)
        if network:
            info = json.loads(network)[0]
            if not info["Internal"] or (info.get("Labels") or {}).get(
                "org.family-learning.pilot"
            ) != str(self.root):
                raise ValueError("Refusing an unrelated or non-private network")
        else:
            run("docker", "network", "create", "--internal", "--label", self.label, self.name)
        network_info = json.loads(run("docker", "network", "inspect", self.name))[0]
        subnet = ipaddress.ip_network(network_info["IPAM"]["Config"][0]["Subnet"])
        address = str(subnet.network_address + 2)
        gateway = network_info["IPAM"]["Config"][0]["Gateway"]
        cloud = state.get("parent_cloud", False)
        cloud_env = []
        if cloud:
            cloud_env += ["-e", "FAMILY_PARENT_CLOUD=1"]
            for key in ("HTTPS_PROXY", "HTTP_PROXY"):
                cloud_env += ["-e", f"{key}=http://{gateway}:3786"]
            cloud_env += ["-e", "NO_PROXY=localhost,127.0.0.1,::1"]
        run(
            "docker",
            "create",
            "--name",
            self.name,
            "--label",
            self.label,
            "--network",
            self.name,
            "--ip",
            address,
            "--memory",
            "4g",
            "--cpus",
            "4",
            "--pids-limit",
            "512",
            "--security-opt",
            "no-new-privileges:true",
            "--log-opt",
            "max-size=5m",
            "--log-opt",
            "max-file=2",
            "-e",
            "FAMILY_LEARNING_ENABLED=1",
            "-e",
            "FAMILY_LEARNING_LOCAL_ONLY=1",
            "-e",
            "FAMILY_PYTHON_ENABLED=1",
            "-e",
            f"FAMILY_LEARNING_ORIGIN=http://127.0.0.1:{state['port']}",
            "-e",
            f"PUID={os.getuid()}",
            "-e",
            f"PGID={os.getgid()}",
            "-v",
            str(self.root / "data") + ":/app/data",
            "-v",
            str(self.root / "broker") + ":/run/family-python:ro",
            *cloud_env,
            state["image"],
        )
        release = Path(state["release"])
        common = "[Unit]\nDescription=Managed Family Learning local pilot\n"
        broker = (
            common
            + "\n[Service]\nWorkingDirectory="
            + str(release).replace("%", "%%")
            + "\nExecStart="
            + " ".join(
                map(
                    quote,
                    [
                        sys.executable,
                        "-B",
                        "-m",
                        "deeptutor.family_learning.python_broker",
                        "--socket",
                        self.root / "broker/broker.sock",
                        "--token",
                        self.root / "broker/token",
                        "--lessons",
                        self.root / "data/system/family-learning",
                    ],
                )
            )
            + "\nRestart=on-failure\nRestartSec=3\nUMask=0077\nNoNewPrivileges=true\n"
        )
        app = (
            common
            + (
                f"Requires={self.name}-parent-cloud.service\nAfter={self.name}-parent-cloud.service\n"
                if cloud
                else ""
            )
            + f"Requires={self.name}-broker.service\nAfter={self.name}-broker.service\n\n[Service]\nExecStart=/usr/bin/docker start -a {self.name}\nExecStop=/usr/bin/docker stop -t 15 {self.name}\nTimeoutStopSec=25\nRestart=on-failure\nRestartSec=3\n"
        )
        proxy = (
            common
            + f"Requires={self.name}-app.service\nAfter={self.name}-app.service\n\n[Service]\nExecStart="
            + " ".join(
                map(
                    quote,
                    [sys.executable, "-B", release / "proxy.py", address, "--port", state["port"]],
                )
            )
            + "\nRestart=on-failure\nRestartSec=3\nUMask=0077\nNoNewPrivileges=true\n"
        )
        self.units.mkdir(parents=True, exist_ok=True)
        callback = (
            common
            + f"Requires={self.name}-app.service\nAfter={self.name}-app.service\n\n[Service]\nExecStart="
            + " ".join(map(quote, [sys.executable, "-B", release / "parent_callback.py", address]))
            + "\nRestart=on-failure\nRestartSec=3\nUMask=0077\nNoNewPrivileges=true\n"
        )
        parent_cloud = (
            common
            + "\n[Service]\nExecStart="
            + " ".join(
                map(
                    quote,
                    [
                        sys.executable,
                        "-B",
                        release / "parent_https_proxy.py",
                        "--bind",
                        gateway,
                        "--peer",
                        address,
                    ],
                )
            )
            + "\nRestart=on-failure\nRestartSec=3\nUMask=0077\nNoNewPrivileges=true\n"
        )
        for suffix, content in [
            ("broker", broker),
            ("app", app),
            ("proxy", proxy),
            ("parent-cloud", parent_cloud),
            ("callback", callback),
        ]:
            target = self.units / (self.name + "-" + suffix + ".service")
            if target.exists() and "Managed Family Learning local pilot" not in target.read_text():
                raise ValueError("Refusing an unrelated user service")
            target.write_text(content)
        (self.root / "state.json").write_text(json.dumps(state))
        run(
            "systemd-analyze",
            "--user",
            "verify",
            *(str(self.units / name) for name in self.services),
        )
        run("systemctl", "--user", "daemon-reload")

    def start(self):
        state = self.state()
        run("systemctl", "--user", "start", self.name + "-proxy.service")
        if state.get("callback_forwarding", False):
            run("systemctl", "--user", "start", self.name + "-callback.service")
        for _ in range(30):
            try:
                with urlopen(
                    f"http://127.0.0.1:{state['port']}/api/auth/status", timeout=2
                ) as response:
                    if not json.load(response).get("enabled", False):
                        raise RuntimeError("Pilot authentication not enabled")
                print(f"Pilot ready: http://127.0.0.1:{state['port']}/family-learning")
                return
            except OSError:
                time.sleep(1)
        self.stop()
        raise RuntimeError("Pilot readiness failed; services stopped")

    def install(self, image, source, parent_cloud=None):
        image_id = run("docker", "image", "inspect", image, "--format", "{{.Id}}")
        if parent_cloud is None:
            parent_cloud = (
                self.state().get("parent_cloud", False)
                if (self.root / "state.json").exists()
                else False
            )
        source = Path(source).resolve()
        if source == self.root or self.root.is_relative_to(source):
            raise ValueError("Pilot must be separate from source data")
        if any(path.is_symlink() for path in source.rglob("*")):
            raise ValueError("Source data contains links; review before copying")
        self.stop()
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", self.port))
        running = run("docker", "ps", "-q").split()
        if running:
            for container in json.loads(run("docker", "inspect", *running)):
                if any(
                    Path(mount["Source"]).resolve() == Path(source).resolve()
                    for mount in container.get("Mounts", [])
                ):
                    raise ValueError("Stop the source tutor before copying its data")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)
        if (self.root / "state.json").exists():
            backup = self.root / "backups" / stamp
            backup.mkdir(parents=True, mode=0o700)
            shutil.copytree(self.root / "data", backup / "data", symlinks=True)
            shutil.copy2(self.root / "state.json", backup / "state.json")
            (self.root / "previous").write_text(str(backup))
        elif (self.root / "data").exists():
            raise ValueError("Unexpected existing pilot data")
        else:
            shutil.copytree(Path(source).resolve(), self.root / "data", symlinks=True)
            settings = self.root / "data/user/settings"
            settings.mkdir(parents=True, exist_ok=True)
            auth = json.loads((settings / "auth.json").read_text())
            if not auth.get("enabled"):
                raise ValueError("Source accounts must have authentication enabled")
            auth["cookie_secure"] = False
            (settings / "auth.json").write_text(json.dumps(auth))
            # Distinct sessions; preserve account passwords but never reuse JWTs.
            secret = self.root / "data/system/auth/auth_secret"
            secret.write_text(secrets.token_urlsafe(48))
            secret.chmod(0o600)
            (settings / "model_catalog.json").write_text(json.dumps({"version": 1, "services": {}}))
        broker = self.root / "broker"
        broker.mkdir(mode=0o700, exist_ok=True)
        if not (broker / "token").exists():
            (broker / "token").write_text(secrets.token_urlsafe(48))
        (broker / "token").chmod(0o600)
        release = self.root / "releases" / stamp
        (release / "deeptutor").mkdir(parents=True, mode=0o700)
        (release / "deeptutor/__init__.py").write_text("")
        source_root = Path(__file__).resolve().parents[1]
        shutil.copytree(
            source_root / "deeptutor/family_learning",
            release / "deeptutor/family_learning",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        shutil.copy2(Path(__file__).with_name("acceptance_proxy.py"), release / "proxy.py")
        shutil.copy2(
            Path(__file__).with_name("acceptance_proxy.py"), release / "acceptance_proxy.py"
        )
        shutil.copy2(Path(__file__).with_name("parent_callback.py"), release / "parent_callback.py")
        shutil.copy2(
            Path(__file__).with_name("parent_https_proxy.py"), release / "parent_https_proxy.py"
        )
        state = {
            "image": image_id,
            "release": str(release),
            "port": self.port,
            "parent_cloud": parent_cloud,
            "callback_forwarding": bool(parent_cloud),
        }
        try:
            self.apply(state)
            self.start()
        except Exception:
            self.stop()
            if (self.root / "previous").exists():
                self.rollback()
            raise

    def rollback(self):
        self.stop()
        if not (self.root / "previous").exists():
            print("First pilot stopped; original tutor and pilot data preserved.")
            return
        backup = Path((self.root / "previous").read_text())
        if backup.parent != self.root / "backups":
            raise ValueError("Unexpected rollback location")
        failed = self.root / ("preserved-before-rollback-" + secrets.token_hex(5))
        (self.root / "data").rename(failed)
        shutil.copytree(backup / "data", self.root / "data", symlinks=True)
        self.apply(json.loads((backup / "state.json").read_text()))
        self.start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "start", "stop", "rollback"])
    parser.add_argument("--root", default=str(Path.home() / ".local/share/family-learning-pilot"))
    parser.add_argument("--name", default="family-learning-pilot")
    parser.add_argument("--port", type=int, default=3784)
    parser.add_argument("--image", default="family-deeptutor:acceptance")
    parser.add_argument("--source-data", type=Path)
    parser.add_argument(
        "--parent-cloud",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Allow fixed OpenAI HTTPS hosts for the parent; learners remain local-only",
    )
    args = parser.parse_args()
    if os.getuid() == 0:
        parser.error("Run as the desktop parent without sudo")
    os.umask(0o077)
    pilot = Pilot(args.root, args.name, args.port)
    if args.action == "install":
        if args.source_data is None:
            parser.error("--source-data is required")
        pilot.install(args.image, args.source_data, args.parent_cloud)
    else:
        getattr(pilot, args.action)()
