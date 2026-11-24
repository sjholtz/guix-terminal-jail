"""Offline contract tests for the original terminal and Python agent launchers."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHERS = ("guix-terminal-jail", "guix-agent-jail")


class TerminalAndAgentCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="guix-cli-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.workspace = self.root / "workspace with spaces"
        self.workspace.mkdir()
        self.env = os.environ.copy()
        self.env.update(
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.root / "xdg-config"),
                "XDG_STATE_HOME": str(self.root / "xdg-state"),
            }
        )
        self.app = self.root / "agent-source"
        self.app.mkdir()
        (self.app / "pyproject.toml").write_text('[project]\nname = "fixture"\n')
        (self.app / "uv.lock").write_text("version = 1\n")
        (self.app / "main.py").write_text('print("ok")\n')

    def run_launcher(self, name, *args, cwd=None):
        return subprocess.run(
            [str(ROOT / name), *map(str, args)],
            env=self.env,
            cwd=cwd or self.workspace,
            capture_output=True,
            text=True,
            check=False,
        )

    def assert_error(self, name, args, expected):
        proc = self.run_launcher(name, *args)
        self.assertNotEqual(proc.returncode, 0, (name, args, proc.stdout))
        self.assertIn(expected, proc.stderr)

    def test_help_does_not_create_state(self):
        for name in LAUNCHERS:
            with self.subTest(name=name):
                proc = self.run_launcher(name, "--help")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("--paths", proc.stdout)
        self.assertFalse((self.root / "xdg-state").exists())

    def test_paths_defaults_to_cwd_without_startup_dependencies(self):
        for name in LAUNCHERS:
            with self.subTest(name=name):
                proc = self.run_launcher(name, "--paths")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn(f"Workspace: {self.workspace}", proc.stdout)
                self.assertIn("Project state:", proc.stdout)
        self.assertFalse((self.root / "xdg-state").exists())
        self.assertFalse((self.root / "xdg-config").exists())

    def test_paths_are_stable_across_both_launchers(self):
        results = [
            self.run_launcher(name, "--paths", self.workspace) for name in LAUNCHERS
        ]
        self.assertTrue(all(item.returncode == 0 for item in results))
        self.assertEqual(results[0].stdout, results[1].stdout)

    def test_init_is_repeatable_across_launchers_without_overwriting_credentials(self):
        terminal = self.run_launcher("guix-terminal-jail", "--init", self.workspace)
        self.assertEqual(terminal.returncode, 0, terminal.stderr)
        credentials = list((self.root / "xdg-config").rglob("credentials.env"))
        self.assertEqual(len(credentials), 1)
        credentials[0].write_text("PRESERVE_ME=yes\n")
        agent = self.run_launcher("guix-agent-jail", "--init", self.workspace)
        self.assertEqual(agent.returncode, 0, agent.stderr)
        self.assertEqual(credentials[0].read_text(), "PRESERVE_ME=yes\n")

    def test_invalid_workspace_is_rejected(self):
        for name in LAUNCHERS:
            with self.subTest(name=name):
                proc = self.run_launcher(name, "--paths", self.root / "does-not-exist")
                self.assertNotEqual(proc.returncode, 0)

    def test_unknown_flags_and_missing_add_package_are_rejected(self):
        for name in LAUNCHERS:
            with self.subTest(name=name):
                self.assert_error(name, ("--not-a-real-option",), "option")
                self.assert_error(name, ("--add-package",), "package")

    def test_terminal_rejects_multiple_project_arguments(self):
        self.assert_error(
            "guix-terminal-jail", (self.workspace, self.workspace), "at most one"
        )

    def test_agent_rejects_multiple_project_arguments(self):
        self.assert_error("guix-agent-jail", (self.workspace, self.workspace), "Use --")

    def test_agent_rejects_app_inside_workspace(self):
        nested = self.workspace / "agent"
        nested.mkdir()
        self.assert_error(
            "guix-agent-jail", ("--app", nested, self.workspace), "must not overlap"
        )

    def test_agent_rejects_workspace_inside_app(self):
        nested = self.app / "subproject"
        nested.mkdir()
        self.assert_error(
            "guix-agent-jail", ("--app", self.app, nested), "must not overlap"
        )

    def test_agent_requires_lockfile(self):
        (self.app / "uv.lock").unlink()
        self.assert_error(
            "guix-agent-jail",
            ("--app", self.app, self.workspace),
            "Application requires",
        )

    def test_agent_entry_must_stay_within_app(self):
        (self.root / "escape.py").write_text("print('escape')\n")
        for entry in ("../escape.py", str(self.root / "escape.py")):
            with self.subTest(entry=entry):
                proc = self.run_launcher(
                    "guix-agent-jail",
                    "--app",
                    self.app,
                    "--entry",
                    entry,
                    self.workspace,
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertTrue(
                    "inside the application" in proc.stderr
                    or "must be relative" in proc.stderr,
                    proc.stderr,
                )

    def test_agent_rejects_missing_entry_before_guix_startup(self):
        self.assert_error(
            "guix-agent-jail",
            ("--app", self.app, "--entry", "not-present.py", self.workspace),
            "realpath",
        )

    def test_agent_rejects_project_configuration_as_app_root(self):
        config = self.home / ".config" / "private-agent"
        config.mkdir(parents=True)
        (config / "main.py").write_text("print('private')\n")
        proc = self.run_launcher("guix-agent-jail", "--app", config, self.workspace)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Mount would expose host configuration", proc.stderr)


if __name__ == "__main__":
    unittest.main()
