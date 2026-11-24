"""Security boundaries and proxy-state logic, without network or Guix calls."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MountAndProxyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="guix-proxy-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.env = os.environ.copy()
        self.env.update(
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.root / "private-config"),
                "XDG_STATE_HOME": str(self.root / "private-state"),
                "WORKSPACE_FOR_TEST": str(self.workspace),
            }
        )
        self.prologue = (
            "set -euo pipefail; umask 077; "
            f"JAIL_DIR={str(ROOT)!r}; "
            'source "$JAIL_DIR/lib/jail-common.sh"; '
            'resolve_workspace "$WORKSPACE_FOR_TEST"; '
        )

    def run_bash(self, command):
        return subprocess.run(
            ["bash", "-c", self.prologue + command],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )

    def test_configuration_directories_and_ancestors_cannot_be_mounted(self):
        self.env["PROTECTED"] = str(self.root / "private-config")
        for forbidden in (
            self.root / "private-config",
            self.root / "private-config" / "guix-terminal" / "credentials.env",
            self.root,
            self.home,
            self.home / ".config",
            Path("/"),
        ):
            with self.subTest(path=forbidden):
                proc = self.run_bash(f"check_mount_source {str(forbidden)!r}")
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("Mount would expose host configuration", proc.stderr)

    def test_symlink_to_configuration_is_rejected(self):
        secret = self.root / "private-config"
        secret.mkdir()
        alias = self.root / "alternate-path"
        alias.symlink_to(secret, target_is_directory=True)
        proc = self.run_bash(f"check_mount_source {str(alias)!r}")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Mount would expose host configuration", proc.stderr)

    def test_equal_sign_in_mount_source_is_rejected(self):
        alias = self.root / "unsafe=name"
        alias.mkdir()
        proc = self.run_bash(f"check_mount_source {str(alias)!r}")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("mapping delimiter", proc.stderr)

    def test_safe_project_mount_is_canonicalized(self):
        alias = self.root / "project-alias"
        alias.symlink_to(self.workspace, target_is_directory=True)
        proc = self.run_bash(
            f"GUIX_ARGS=(); add_mount share {str(alias)!r} /workspace; "
            'printf "%s\\n" "${GUIX_ARGS[@]}"'
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), f"--share={self.workspace}=/workspace")

    def test_proxy_record_rejected_if_pid_or_process_start_changes(self):
        records = (
            'mkdir -p "$WORKSPACE_STATE_DIR"; '
            'printf "12345\\n" > "$PID_FILE"; '
            'printf "99\\n" > "$START_FILE"; '
            'printf "8080\\n" > "$PORT_FILE"; '
            "process_start() { echo 100; }; "
            "owns_proxy_port() { return 0; }; "
            "if load_proxy; then echo accepted; else echo rejected; fi"
        )
        proc = self.run_bash(records)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "rejected")

    def test_proxy_record_requires_matching_port_owner(self):
        records = (
            'mkdir -p "$WORKSPACE_STATE_DIR"; '
            'printf "12345\\n" > "$PID_FILE"; '
            'printf "99\\n" > "$START_FILE"; '
            'printf "8080\\n" > "$PORT_FILE"; '
            "process_start() { echo 99; }; "
            "owns_proxy_port() { return 1; }; "
            "if load_proxy; then echo accepted; else echo rejected; fi"
        )
        proc = self.run_bash(records)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "rejected")

    def test_verified_proxy_record_is_accepted(self):
        proc = self.run_bash(
            'mkdir -p "$WORKSPACE_STATE_DIR"; '
            'printf "12345\\n" > "$PID_FILE"; '
            'printf "99\\n" > "$START_FILE"; '
            'printf "8080\\n" > "$PORT_FILE"; '
            "process_start() { echo 99; }; "
            'owns_proxy_port() { [[ "$1" == 12345 && "$2" == 8080 ]]; }; '
            'load_proxy; echo "$PROXY_PID:$PORT"'
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "12345:8080")

    def test_proxy_reuse_refuses_changed_credentials_or_addon(self):
        proc = self.run_bash(
            'mkdir -p "$WORKSPACE_STATE_DIR"; '
            "load_proxy() { PROXY_PID=12345; PORT=8080; return 0; }; "
            'printf "other-config\\n" > "$WORKSPACE_STATE_DIR/proxy_config"; '
            "ensure_mitmproxy"
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("different credential file or addon", proc.stderr)

    def test_proxy_reuse_with_same_fingerprint_never_starts_new_proxy(self):
        proc = self.run_bash(
            'mkdir -p "$WORKSPACE_STATE_DIR"; '
            'proxy_config=$(printf "%s\\0" "$MITM_SCRIPT" "$CONFIG_DIR" '
            '"$CREDENTIALS_FILE" "${KEY_INJECTOR_CONFIG:-}" | sha256sum '
            "| awk '{print $1}'); "
            'printf "%s\\n" "$proxy_config" > "$WORKSPACE_STATE_DIR/proxy_config"; '
            "load_proxy() { PROXY_PID=12345; PORT=8080; return 0; }; "
            "ensure_mitmproxy; echo reuse-ok"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("reuse-ok", proc.stdout)
        self.assertIn("Reusing mitmdump", proc.stderr)

    def test_failed_proxy_start_cleans_all_candidate_state(self):
        # A fake executable that exits immediately exercises readiness failure
        # and retry cleanup without binding a socket or contacting the network.
        fake_bin = self.root / "fake-tools"
        fake_bin.mkdir()
        mitmdump = fake_bin / "mitmdump"
        mitmdump.write_text("#!/usr/bin/env bash\nexit 1\n")
        mitmdump.chmod(0o755)
        self.env["PATH"] = f"{fake_bin}:{self.env['PATH']}"
        proc = self.run_bash(
            'mkdir -p "$WORKSPACE_STATE_DIR" "$CONFIG_DIR"; '
            'printf "FAKE_CREDENTIAL=yes\\n" > "$CREDENTIALS_FILE"; '
            "owns_proxy_port() { return 1; }; "
            "if ensure_mitmproxy; then echo unexpected; else echo startup-failed; fi"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "startup-failed")
        state_dir = next(
            (self.root / "private-state" / "guix-terminal/projects").iterdir()
        )
        for name in ("mitmdump.pid", "mitmdump.start", "mitmdump.port", "proxy_config"):
            with self.subTest(name=name):
                self.assertFalse((state_dir / name).exists())
        log = (state_dir / "mitmdump.log").read_text()
        self.assertIn("trying 127.0.0.1:8080", log)
        self.assertIn("trying 127.0.0.1:8089", log)

    def test_cleanup_removes_stale_clients_and_persists_history(self):
        proc = self.run_bash(
            'mkdir -p "$WORKSPACE_STATE_DIR" "$CLIENTS_DIR" "$CONTAINER_HOME"; '
            'printf "old history\\n" > "$CONTAINER_HOME/.bash_history"; '
            'printf "77\\n" > "$CLIENTS_DIR/999999999"; '
            'CLIENT_FILE="$CLIENTS_DIR/current"; touch "$CLIENT_FILE"; '
            "process_start() { return 1; }; load_proxy() { return 1; }; "
            'exec 9> "$WORKSPACE_STATE_DIR/workspace.lock"; '
            "cleanup"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        state_dir = next(
            (self.root / "private-state" / "guix-terminal/projects").iterdir()
        )
        self.assertFalse((state_dir / "clients" / "999999999").exists())
        self.assertFalse((state_dir / "home").exists())
        self.assertEqual((state_dir / "bash_history").read_text(), "old history\n")

    def test_cleanup_does_not_remove_home_with_other_live_client(self):
        proc = self.run_bash(
            'mkdir -p "$WORKSPACE_STATE_DIR" "$CLIENTS_DIR" "$CONTAINER_HOME"; '
            'printf "55\\n" > "$CLIENTS_DIR/4242"; '
            'CLIENT_FILE="$CLIENTS_DIR/current"; touch "$CLIENT_FILE"; '
            'process_start() { if [[ "$1" == 4242 ]]; '
            "then echo 55; else return 1; fi; }; "
            "load_proxy() { return 1; }; "
            'exec 9> "$WORKSPACE_STATE_DIR/workspace.lock"; '
            "cleanup"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        state_dir = next(
            (self.root / "private-state" / "guix-terminal/projects").iterdir()
        )
        self.assertTrue((state_dir / "clients" / "4242").exists())
        self.assertTrue((state_dir / "home").exists())

    def test_process_start_rejects_non_numeric_and_missing_pid(self):
        proc = self.run_bash(
            "for value in invalid -1 999999999; do "
            'if process_start "$value"; then echo unexpected; fi; done; echo ok'
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
