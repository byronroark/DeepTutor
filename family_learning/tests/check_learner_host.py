"""Checks run without root, Docker, credentials or changes to the host."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "learner_host.py"
spec = importlib.util.spec_from_file_location("learner_host", MODULE)
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class AppUpdateTests(unittest.TestCase):
    def test_update_refuses_non_root_and_checksum_mismatch_before_docker(self):
        spec = importlib.util.spec_from_file_location(
            "host_update", MODULE.with_name("update_host.py")
        )
        update = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(update)
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "app.tar"
            archive.write_bytes(b"synthetic archive")
            archive.chmod(0o600)
            arguments = [
                "update_host.py",
                "--archive",
                str(archive),
                "--sha256",
                "0" * 64,
                "--image",
                "sha256:" + "1" * 64,
            ]
            with patch.object(sys, "argv", arguments), patch.object(update, "run") as run:
                with patch.object(update.os, "getuid", return_value=1000):
                    with self.assertRaises(SystemExit):
                        update.main()
                with (
                    patch.object(update.os, "getuid", return_value=0),
                    patch.dict(os.environ, {"SUDO_UID": str(archive.stat().st_uid)}),
                ):
                    with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                        update.main()
                run.assert_not_called()


class LearnerHostTests(unittest.TestCase):
    def test_recovery_lock_uses_service_home_in_isolated_python(self):
        recovery = MODULE.parents[1] / "deeptutor/family_learning/recovery.py"
        with tempfile.TemporaryDirectory() as folder:
            subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-c",
                    "import runpy,sys; module=runpy.run_path(sys.argv[1]); "
                    "lock=module['broker_lock'](); lock.__enter__(); lock.__exit__(None,None,None)",
                    str(recovery),
                ],
                env={**os.environ, "HOME": folder},
                check=True,
            )
            self.assertTrue((Path(folder) / ".local/state/family-learning-runner/lock").is_file())

    def test_resume_requires_matching_preparing_state_and_trusted_code(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            code = root / "code"
            code.mkdir()
            state = root / "installation.json"
            state.write_text(json.dumps({"phase": "ready", "archive_sha256": "a" * 64}))
            with (
                patch.object(host, "ROOT", root),
                patch.object(host, "CODE", code),
                patch.object(host.os, "getuid", return_value=0),
            ):
                real_lstat = Path.lstat

                def root_owned(path, *args, **kwargs):
                    info = real_lstat(path, *args, **kwargs)
                    return os.stat_result(
                        (
                            info.st_mode,
                            info.st_ino,
                            info.st_dev,
                            info.st_nlink,
                            0,
                            info.st_gid,
                            info.st_size,
                            info.st_atime,
                            info.st_mtime,
                            info.st_ctime,
                        )
                    )

                with patch.object(Path, "lstat", autospec=True, side_effect=root_owned):
                    with self.assertRaisesRegex(ValueError, "matching interrupted"):
                        host.check_resume("a" * 64)
                    state.write_text(json.dumps({"phase": "preparing", "archive_sha256": "b" * 64}))
                    with self.assertRaisesRegex(ValueError, "matching interrupted"):
                        host.check_resume("a" * 64)
                    state.write_text(json.dumps({"phase": "preparing", "archive_sha256": "a" * 64}))
                    self.assertEqual(host.check_resume("a" * 64)["phase"], "preparing")
                    (code / "linked").symlink_to("/etc/passwd")
                    with self.assertRaisesRegex(ValueError, "root-owned"):
                        host.check_resume("a" * 64)

    def test_refuses_non_root_before_running_commands(self):
        with patch.object(host.os, "getuid", return_value=1000), patch.object(host, "run") as run:
            with self.assertRaisesRegex(ValueError, "sudo"):
                host.install("/missing", "/missing", "0" * 64)
            run.assert_not_called()

    def test_checksum_failure_never_runs_privileged_commands(self):
        uid = os.getuid()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "deeptutor/family_learning").mkdir(parents=True)
            for file in [
                "learner_bootstrap.py",
                "acceptance_proxy.py",
                "deeptutor/family_learning/python_broker.py",
            ]:
                (root / file).write_text("")
            (root / "image.tar").write_bytes(b"not the expected image")
            with (
                patch.dict(os.environ, {"SUDO_UID": str(uid)}),
                patch.object(host.os, "getuid", return_value=0),
                patch.object(host, "run") as run,
            ):
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    host.install(root, root / "image.tar", "0" * 64, "sha256:" + "1" * 64)
                run.assert_not_called()

    def test_staging_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "link").symlink_to("/etc/passwd")
            with self.assertRaisesRegex(ValueError, "unlinked"):
                host.checked_source(root)

    def test_broker_uses_isolated_python_and_immutable_code(self):
        services = host.units("sha256:test", "172.30.0.2", 950, 950)
        broker = services["broker"]
        self.assertIn("User=familylearn", broker)
        self.assertIn("Environment=HOME=/var/lib/family-learning/broker", broker)
        self.assertIn("python3 -I -B /opt/family-learning/broker_entry.py", broker)
        self.assertIn("ProtectHome=true", broker)
        self.assertIn("ProtectSystem=strict", broker)
        self.assertNotIn("User=odin", broker)
        self.assertIn("--port 3785", services["web"])


if __name__ == "__main__":
    unittest.main()
