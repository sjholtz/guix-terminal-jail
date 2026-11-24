# Testing and host acceptance procedure

## A. Offline regression tests (run on any Linux system with Python 3)

From the project directory:

```bash
python3 -m unittest discover -s tests -v
find . -type f \( -name '*.sh' -o -name 'guix-*-jail' \) \
  -exec bash -n {} \;
```

The tests check argument parsing, `--paths` side-effect freedom, idempotent
`--init`, resolved host npm layout and native package, stable Codex workdir
mounts, bounded mount scope, rejection of symlinked `~/.codex`, standalone
updater mount isolation, and independently selectable package profiles.

**These tests simulate the host npm package and inspect constructed Guix
arguments.** They do not launch Guix, contact OpenAI, or validate a real Codex
native binary. The actual Guix integration must run on your machine.

## B. Host discovery (before launching)

```bash
command -v codex
readlink -f "$(command -v codex)"
npm root -g
codex --version
codex login status

guix-codex-cli-jail --paths "$HOME/projects/test-codex-a"
```

Expected: the npm entry resolves into `@openai/codex/bin/codex.js`, the host
CLI reports its current version and ChatGPT login, and `--paths` displays a
stable project-specific CWD without starting the proxy or changing state.

## C. First launch in a disposable workspace

```bash
mkdir -p "$HOME/projects/test-codex-a" "$HOME/projects/test-codex-b"
printf 'safe test content\n' > "$HOME/projects/test-codex-a/README.txt"

guix-codex-cli-jail --init "$HOME/projects/test-codex-a"
# Edit project credentials or use previously configured shared credentials.

guix-codex-cli-jail "$HOME/projects/test-codex-a" -- --version
guix-codex-cli-jail "$HOME/projects/test-codex-a" -- login status
```

Expected: the jail CLI version matches the host npm version; login status
reports a ChatGPT login (assuming file-based auth); the proxy starts and is
stopped after the last command exits; the selected project is the only
project directory exposed. Check `--paths` for the project's `mitmdump.log`.

The first Guix launch may download packages. If login fails, do **not** weaken
sandboxing; investigate Codex credential storage and proxy/CA behavior.

## D. Session persistence and cross-project separation

1. Start `guix-codex-cli-jail "$HOME/projects/test-codex-a"` and create a short
   test session that mentions the file `README.txt`, then exit.
2. Run `guix-codex-cli-jail "$HOME/projects/test-codex-a" -- resume --last`.
   The same project session should be offered.
3. Start a separate session under
   `guix-codex-cli-jail "$HOME/projects/test-codex-b"`; exit.
4. Run `guix-codex-cli-jail "$HOME/projects/test-codex-a" -- resume --last`
   again. The most recent **A** session should be selected, not B.
5. Run `guix-codex-cli-jail "$HOME/projects/test-codex-a" -- resume --all`.
   The selection view may include B or older host sessions. Their recorded
   directories must not be assumed to be translated automatically.

To confirm the actual working directory during a Codex session, ask the CLI
to run `pwd` (with normal command approval). Expected:
`/workspaces/test-codex-a-<12-hex-hash>`. The project is also accessible at
`/workspace`, but Codex does not start there.

## E. Codex permissions and nested sandboxing

In the disposable A project, ask Codex to inspect a file in the project and
then to read an **unmounted**, harmless test file elsewhere on the host.
The unmounted path should not exist within the Guix filesystem. Also ask for
a proposed write to an unexpected path and ensure approval/sandbox behavior
matches your intent. Do not put real secrets into test files.

A successful read within `/workspace` does not prove the inner Codex sandbox
is active. Review any Bubblewrap, namespace, or sandbox errors. Nested sandbox
failure is host-dependent. Do not automatically enable bypass flags. In
particular, remember `~/.codex` itself is deliberately mounted read/write.

## F. Standalone fallback and explicit updates (optional)

```bash
guix-codex-cli-jail --update

guix-codex-cli-jail --backend standalone "$HOME/projects/test-codex-a" -- --version
guix-codex-cli-jail --backend standalone "$HOME/projects/test-codex-a" -- login status
```

Expected: installer executes once when requested, produces a binary under the
persistent state root, and subsequent standalone launches reuse that binary.
Check that your host's `codex --version` did not change as a result of
`--update`. The update code must **not** have `/workspace` or `~/.codex` mounted.

## G. Regression checks for existing launchers

```bash
guix-terminal-jail --paths "$HOME/projects/test-codex-a"
guix-terminal-jail "$HOME/projects/test-codex-a"
# In the interactive shell: command -v tar gzip gawk python3 uv node

guix-agent-jail --paths "$HOME/projects/test-codex-a"
# If you have a known-good agent application:
guix-agent-jail --app "$HOME/bin/myagent" "$HOME/projects/test-codex-a" -- --help
```

Expected: terminal/agent behavior unchanged, package profiles independently
selected, and no host `~/.config` mount allowed.

## H. Concurrent sessions and cleanup

Open two terminals with the **same** project, one Codex and one terminal jail.
They should use the same workspace proxy until the last session exits. Try a
separate project simultaneously; it should use its own proxy/state. After both
exit, check that `mitmdump` is no longer running for these projects and that
`mitmdump.log` contains full timestamps. Interrupted sessions merit an
additional test of cleanup and orphan-process handling.

## Results / limits

- The checked-in tests validate launcher logic and mount intentions, not Guix
  kernel isolation or external software operation.
- Actual npm-native dependency compatibility, TLS, ChatGPT authentication,
  `resume` behavior, nested Bubblewrap sandboxing, and host proxy reuse
  **require the above tests on the real Guix system**.
- Never make claims of production isolation on the basis of the offline
  suite alone.
