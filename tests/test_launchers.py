"""Offline regression checks for launcher parsing, packages, and mount scope.

These do not replace a Guix/mitmproxy/Codex integration test on the host.
"""

import os
import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="guix-jail-tests-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.project = self.base / "project one"
        self.project.mkdir()
        self.config = self.base / "config"
        self.state = self.base / "state"
        self.package = self.base / "npm" / "@openai" / "codex"
        (self.package / "bin").mkdir(parents=True)
        (self.package / "bin" / "codex.js").write_text("#!/usr/bin/env node\n")
        (self.package / "package.json").write_text('{"name":"@openai/codex"}\n')
        arch = platform.machine()
        if arch == "x86_64":
            triple, native_name = "x86_64-unknown-linux-musl", "codex-linux-x64"
        elif arch in ("aarch64", "arm64"):
            triple, native_name = "aarch64-unknown-linux-musl", "codex-linux-arm64"
        else:
            self.skipTest(f"Codex npm test fixture does not support {arch}")
        self.triple = triple
        self.native_name = native_name
        self.native = self.base / "npm" / "@openai" / native_name
        (self.native / "vendor" / triple / "bin").mkdir(parents=True)
        binary = self.native / "vendor" / triple / "bin" / "codex"
        binary.write_text("native executable placeholder\n")
        binary.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update(
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.config),
                "XDG_STATE_HOME": str(self.state),
                "GUIX_CODEX_HOST_ENTRY": str(self.package / "bin" / "codex.js"),
                "PROJECT_FOR_TEST": str(self.project),
            }
        )
        self.prologue = (
            "set -euo pipefail; "
            f"JAIL_DIR={str(ROOT)!r}; "
            'source "$JAIL_DIR/lib/jail-common.sh"; '
            'resolve_workspace "$PROJECT_FOR_TEST"; '
            'source "$JAIL_DIR/lib/codex-common.sh"; '
        )

    def run_shell(self, command, *, success=True):
        proc = subprocess.run(
            ["bash", "-c", command],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        if success and proc.returncode:
            self.fail(
                f"shell returned {proc.returncode}:\n{proc.stderr}\n{proc.stdout}"
            )
        return proc

    def test_syntax(self):
        scripts = [
            ROOT / name
            for name in (
                "guix-terminal-jail",
                "guix-agent-jail",
                "guix-codex-cli-jail",
            )
        ]
        scripts.extend((ROOT / "lib").glob("*.sh"))
        scripts.extend(ROOT / name for name in ("environment.sh", "bashrc"))
        for script in scripts:
            with self.subTest(script=script.name):
                subprocess.run(
                    ["bash", "-n", str(script)],
                    check=True,
                )

    def test_paths_requires_no_codex_or_guix_and_no_side_effects(self):
        env = dict(self.env)
        env.pop("GUIX_CODEX_HOST_ENTRY")
        proc = subprocess.run(
            [str(ROOT / "guix-codex-cli-jail"), "--paths", str(self.project)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Codex project CWD: /workspaces/project_one-", proc.stdout)
        self.assertIn("Codex backend: host", proc.stdout)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.config.exists())

    def test_init_preserves_credentials(self):
        command = [str(ROOT / "guix-codex-cli-jail"), "--init", str(self.project)]
        subprocess.run(
            command, env=self.env, check=True, capture_output=True, text=True
        )
        creds = list(self.config.rglob("credentials.env"))
        self.assertEqual(len(creds), 1)
        creds[0].write_text("CUSTOM_KEY=don't overwrite\n")
        subprocess.run(
            command, env=self.env, check=True, capture_output=True, text=True
        )
        self.assertEqual(creds[0].read_text(), "CUSTOM_KEY=don't overwrite\n")

    def test_host_package_and_native_dependency_resolve(self):
        proc = self.run_shell(
            self.prologue
            + 'prepare_host_codex; printf "%s\\n%s\\n" "$CODEX_HOST_PACKAGE" "$CODEX_NATIVE_MOUNT"'
        )
        self.assertEqual(
            proc.stdout.splitlines(), [str(self.package), str(self.native)]
        )

    def test_nested_native_package_needs_no_second_mount(self):
        nested = self.package / "node_modules" / "@openai" / self.native_name
        nested.parent.mkdir(parents=True)
        shutil.move(self.native, nested)
        proc = self.run_shell(
            self.prologue + 'prepare_host_codex; printf "[%s]\\n" "$CODEX_NATIVE_MOUNT"'
        )
        self.assertEqual(proc.stdout.strip(), "[]")

    def test_guix_package_groups_are_forwarded(self):
        fake_bin = self.base / "bin"
        fake_bin.mkdir()
        fake_guix = fake_bin / "guix"
        fake_guix.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$TEST_GUIX_ARGS"\n')
        fake_guix.chmod(0o755)
        self.env["PATH"] = f"{fake_bin}:{self.env.get('PATH', '')}"
        self.env["TEST_GUIX_ARGS"] = str(self.base / "guix-args.txt")
        self.run_shell(
            self.prologue + "select_launcher_packages codex-host; "
            "GUIX_ARGS=(shell --container); add_package ripgrep; "
            "run_container true"
        )
        args = Path(self.env["TEST_GUIX_ARGS"]).read_text().splitlines()
        self.assertIn("node", args)
        self.assertIn("tar", args)
        self.assertIn("gzip", args)
        self.assertIn("gawk", args)
        self.assertIn("ripgrep", args)
        self.assertNotIn("uv", args)
        self.assertNotIn("python", args)

    def test_missing_platform_package_rejected(self):
        binary = self.native / "vendor" / self.triple / "bin/codex"
        binary.unlink()
        proc = self.run_shell(self.prologue + "prepare_host_codex", success=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Missing executable native Codex binary", proc.stderr)

    def build_mounts(self, backend, action="run"):
        setup = (
            'mkdir -p "$CONTAINER_HOME" "$HOME/.cache/uv" '
            '"$HOME/.local/share/uv" "$HOME/.mitmproxy"; '
            'touch "$HOME/.mitmproxy/mitmproxy-ca-cert.cer"; '
            f"CODEX_BACKEND={backend}; CODEX_ACTION={action}; "
            'if [[ "$CODEX_ACTION" != update ]]; then prepare_codex_home; fi; '
            'if [[ "$CODEX_BACKEND" == host ]]; then prepare_host_codex; '
            "else prepare_standalone_codex; fi; "
            'if [[ "$CODEX_ACTION" == update ]]; then MOUNT_WORKSPACE=0; fi; '
            "build_guix_args; add_codex_mounts; "
            'printf "%s\\n" "${GUIX_ARGS[@]}";'
        )
        return self.run_shell(self.prologue + setup).stdout.splitlines()

    def test_host_mounts_are_scoped_and_cwd_unique(self):
        args = self.build_mounts("host")
        self.assertIn(f"--share={self.project}=/workspace", args)
        self.assertTrue(
            any(
                arg.startswith(f"--share={self.project}=/workspaces/project_one-")
                for arg in args
            )
        )
        self.assertIn(f"--share={self.home}/.codex={self.home}/.codex", args)
        self.assertIn(
            f"--expose={self.package}=/opt/host-codex/node_modules/@openai/codex", args
        )
        self.assertIn(
            f"--expose={self.native}=/opt/host-codex/node_modules/@openai/{self.native_name}",
            args,
        )
        self.assertFalse(any(arg.startswith("--expose=/usr/local") for arg in args))
        self.assertFalse(any(arg.endswith("=/usr/local") for arg in args))

    def test_update_excludes_project_and_authentication(self):
        args = self.build_mounts("standalone", "update")
        self.assertFalse(
            any("=/workspace" in arg or "/workspaces/" in arg for arg in args)
        )
        self.assertFalse(any("/.codex" in arg for arg in args))
        self.assertTrue(any("=/opt/guix-codex-install" in arg for arg in args))

    def test_configuration_mount_is_still_forbidden(self):
        self.config.mkdir()
        bad = self.run_shell(
            self.prologue + 'check_mount_source "$XDG_CONFIG_HOME"', success=False
        )
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("Mount would expose host configuration", bad.stderr)

    def test_symlinked_codex_home_rejected(self):
        self.config.mkdir()
        (self.home / ".codex").symlink_to(self.config, target_is_directory=True)
        bad = self.run_shell(self.prologue + "prepare_codex_home", success=False)
        self.assertNotEqual(bad.returncode, 0)
        self.assertTrue("configuration" in bad.stderr or "symlink" in bad.stderr)

    def test_package_profiles(self):
        proc = self.run_shell(
            self.prologue
            + 'select_launcher_packages terminal; printf "TERM:%s\\n" "${LAUNCHER_GUIX_PACKAGES[*]}"; '
            'select_launcher_packages agent; printf "AGENT:%s\\n" "${LAUNCHER_GUIX_PACKAGES[*]}"; '
            'select_launcher_packages codex-host; printf "HOST:%s\\n" "${LAUNCHER_GUIX_PACKAGES[*]}"; '
            'select_launcher_packages codex-standalone; printf "STANDALONE:%s\\n" "${LAUNCHER_GUIX_PACKAGES[*]}"; '
            'printf "BASE:%s\\n" "${BASE_GUIX_PACKAGES[*]}";'
        )
        lines = dict(line.split(":", 1) for line in proc.stdout.splitlines())
        for name in ("TERM", "AGENT"):
            self.assertTrue(
                {"gcc-toolchain", "uv", "python", "node"}.issubset(
                    set(lines[name].split())
                )
            )
        self.assertEqual(lines["HOST"].split(), ["node", "procps"])
        self.assertEqual(lines["STANDALONE"].strip(), "procps")
        self.assertTrue({"tar", "gawk", "gzip"}.issubset(set(lines["BASE"].split())))

    def test_update_rejects_host_backend_and_codex_args(self):
        for argv in (("--update", "--backend", "host"), ("--update", "--", "resume")):
            with self.subTest(argv=argv):
                proc = subprocess.run(
                    [str(ROOT / "guix-codex-cli-jail"), *argv],
                    env=self.env,
                    cwd=self.project,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
