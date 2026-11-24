"""Offline invariants for XDG initialization and legacy-state migration."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "lib/prepare-project.py"


class ProjectPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="guix-project-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project with spaces"
        self.project.mkdir()
        self.config = self.root / "config" / "project-one"
        self.state = self.root / "state" / "project-one"
        self.legacy = self.root / "legacy" / "project-one"
        self.template = self.root / "credentials-template"
        self.template.write_text("API_KEY=placeholder\n")

    def run_prepare(self, action="init"):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                action,
                str(self.project),
                str(self.config),
                str(self.state),
                str(self.legacy),
                str(self.template),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def assert_prepared(self, action="init"):
        completed = self.run_prepare(action)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_init_creates_private_credentials_and_stable_identity(self):
        self.assert_prepared()
        expected = os.fsencode(self.project) + b"\n"
        self.assertEqual((self.config / "project_path").read_bytes(), expected)
        self.assertEqual((self.state / "project_path").read_bytes(), expected)
        self.assertEqual(
            (self.config / "credentials.env").read_text(),
            "API_KEY=placeholder\n",
        )
        self.assertEqual(
            (self.config / "credentials.env").stat().st_mode & 0o777, 0o600
        )

    def test_repeated_init_does_not_replace_credentials(self):
        self.assert_prepared()
        credentials = self.config / "credentials.env"
        credentials.write_text("CUSTOM_TOKEN=keep-me\n")
        self.template.write_text("API_KEY=new-default\n")
        self.assert_prepared()
        self.assertEqual(credentials.read_text(), "CUSTOM_TOKEN=keep-me\n")

    def test_run_creates_state_but_not_configuration_or_credentials(self):
        self.assert_prepared("run")
        self.assertTrue((self.state / "project_path").exists())
        self.assertFalse(self.config.exists())

    def test_state_identity_collision_is_rejected_without_overwrite(self):
        self.assert_prepared()
        marker = self.state / "project_path"
        marker.write_text("/some/other/project\n")
        bad = self.run_prepare()
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("identity differs", bad.stderr)
        self.assertEqual(marker.read_text(), "/some/other/project\n")

    def test_config_identity_collision_is_rejected(self):
        self.assert_prepared()
        (self.config / "project_path").write_text("/wrong/project\n")
        bad = self.run_prepare()
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("identity differs", bad.stderr)

    def test_idle_legacy_state_is_migrated(self):
        self.legacy.mkdir(parents=True)
        (self.legacy / "project_path").write_bytes(os.fsencode(self.project) + b"\n")
        (self.legacy / "mitmdump.log").write_text("historic log\n")
        (self.legacy / "clients").mkdir()
        (self.legacy / "clients" / "999999999").write_text("1\n")
        self.assert_prepared("run")
        self.assertFalse(self.legacy.exists())
        self.assertEqual((self.state / "mitmdump.log").read_text(), "historic log\n")
        self.assertTrue((self.state / "workspace.lock").exists())

    def test_conflicting_legacy_and_new_state_are_not_merged(self):
        self.legacy.mkdir(parents=True)
        self.state.mkdir(parents=True)
        bad = self.run_prepare("run")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("Both legacy and new state exist", bad.stderr)
        self.assertTrue(self.legacy.exists())
        self.assertTrue(self.state.exists())

    def test_active_legacy_client_blocks_migration(self):
        self.legacy.mkdir(parents=True)
        clients = self.legacy / "clients"
        clients.mkdir()
        fields = (
            Path(f"/proc/{os.getpid()}/stat").read_bytes().rsplit(b") ", 1)[1].split()
        )
        (clients / str(os.getpid())).write_bytes(fields[19] + b"\n")
        bad = self.run_prepare("run")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("active legacy session", bad.stderr)
        self.assertTrue(self.legacy.exists())
        self.assertFalse(self.state.exists())

    def test_simultaneous_initialization_does_not_corrupt_credentials(self):
        args = [
            sys.executable,
            str(SCRIPT),
            "init",
            str(self.project),
            str(self.config),
            str(self.state),
            str(self.legacy),
            str(self.template),
        ]
        children = [
            subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(3)
        ]
        for child in children:
            stdout, stderr = child.communicate(timeout=15)
            self.assertEqual(child.returncode, 0, (stdout, stderr))
        self.assertEqual(
            (self.config / "credentials.env").read_text(), "API_KEY=placeholder\n"
        )


if __name__ == "__main__":
    unittest.main()
