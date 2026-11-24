"""Offline checks for reproducible, private uv application snapshots."""

import importlib.util
import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, cast
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "lib/stage-app.py"


def load_stager():
    spec = importlib.util.spec_from_file_location("guix_stage_app_for_tests", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load stage-app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(Any, module)


class AppStagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="guix-stage-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.state = self.root / "state"
        self.state.mkdir()
        (self.source / "pyproject.toml").write_text(
            '[project]\nname = "example-agent"\nversion = "0.1.0"\n'
        )
        (self.source / "uv.lock").write_text(
            'version = 1\n[[package]]\nname = "example-agent"\n'
            'source = { editable = "." }\n'
            '[[package]]\nname = "remote-dependency"\n'
            'source = { registry = "https://example.invalid" }\n'
        )
        (self.source / "main.py").write_text('print("hello")\n')
        self.stager = load_stager()

    def run_stage(self):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(self.source), str(self.state)],
            capture_output=True,
            text=True,
            check=False,
        )

    def assert_staged(self):
        proc = self.run_stage()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.split()

    def test_stage_copies_source_and_emits_only_local_packages(self):
        fields = self.assert_staged()
        self.assertEqual(fields[0], (self.state / "source-hash").read_text().strip())
        self.assertEqual(fields[1:], ["example-agent"])
        self.assertEqual(
            (self.state / "source" / "main.py").read_text(), 'print("hello")\n'
        )

    def test_unchanged_source_does_not_replace_snapshot(self):
        self.assert_staged()
        snapshot = self.state / "source"
        (snapshot / "created-during-build.txt").write_text("retain build artifacts")
        self.assert_staged()
        self.assertEqual(
            (snapshot / "created-during-build.txt").read_text(),
            "retain build artifacts",
        )

    def test_modified_source_refreshes_snapshot(self):
        first_hash = self.assert_staged()[0]
        (self.source / "main.py").write_text('print("changed")\n')
        second_hash = self.assert_staged()[0]
        self.assertNotEqual(first_hash, second_hash)
        self.assertEqual(
            (self.state / "source" / "main.py").read_text(),
            'print("changed")\n',
        )
        self.assertFalse((self.state / "source.old").exists())

    def test_ignored_virtualenv_and_bytecode_do_not_change_hash(self):
        first = self.stager.fingerprint(self.source)
        for name in (".venv", "__pycache__"):
            folder = self.source / name
            folder.mkdir()
            (folder / "generated.pyc").write_text("opaque generated artifact")
        self.assertEqual(first, self.stager.fingerprint(self.source))
        self.assert_staged()
        self.assertFalse((self.state / "source" / ".venv").exists())
        self.assertFalse((self.state / "source" / "__pycache__").exists())

    def test_symlinks_preserved_without_following_outside_directory(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("never stage")
        (self.source / "outside-link").symlink_to(outside, target_is_directory=True)
        self.assert_staged()
        link = self.state / "source" / "outside-link"
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), str(outside))
        self.assertFalse((self.state / "source" / "secret.txt").exists())
        # The target contents are not incorporated into the source fingerprint.
        first = self.stager.fingerprint(self.source)
        (outside / "secret.txt").write_text("updated")
        self.assertEqual(first, self.stager.fingerprint(self.source))

    def test_readonly_source_becomes_writable_only_in_snapshot(self):
        original = self.source / "main.py"
        original.chmod(0o400)
        self.assert_staged()
        copied = self.state / "source" / "main.py"
        self.assertTrue(copied.stat().st_mode & stat.S_IWUSR)
        self.assertFalse(original.stat().st_mode & stat.S_IWUSR)

    def test_all_local_dependency_source_forms_are_listed(self):
        (self.source / "uv.lock").write_text(
            "version = 1\n"
            + "".join(
                f'[[package]]\nname = "local-{kind}"\n'
                f'source = {{ {kind} = "../dep" }}\n'
                for kind in ("directory", "editable", "virtual", "path")
            )
        )
        fields = self.assert_staged()
        self.assertEqual(
            fields[1:],
            [
                "example-agent",
                "local-directory",
                "local-editable",
                "local-path",
                "local-virtual",
            ],
        )

    def test_invalid_package_name_rejected(self):
        (self.source / "uv.lock").write_text(
            'version = 1\n[[package]]\nname = "../../escape"\n'
            'source = { path = "../dep" }\n'
        )
        proc = self.run_stage()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("invalid package name", proc.stderr)

    def test_detects_source_mutation_during_copy_without_publishing(self):
        original_hash = self.stager.fingerprint(self.source)
        with (
            mock.patch.object(
                self.stager,
                "fingerprint",
                side_effect=[original_hash, "changed-mid-copy"],
            ),
            self.assertRaisesRegex(RuntimeError, "changed during setup"),
            redirect_stdout(io.StringIO()),
        ):
            self.stager.stage(self.source, self.state)
        self.assertFalse((self.state / "source").exists())
        self.assertFalse((self.state / "source.new").exists())
        self.assertFalse((self.state / "source-hash").exists())


if __name__ == "__main__":
    unittest.main()
