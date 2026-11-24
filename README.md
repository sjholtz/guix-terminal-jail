# Guix Terminal Jail

Run a development shell, a uv-managed Python agent, or the OpenAI Codex CLI
inside a [GNU Guix](https://guix.gnu.org/) Linux container with an
explicitly selected writable project and a host-side mitmproxy for outbound
HTTPS requests.

**Author:** Steven J Holtz  
**License:** GPL-3.0 (see [LICENSE](LICENSE)).

Three commands share project identity, private XDG configuration/state,
mitmproxy lifecycle, mount validation, log management, and cleanup:

| Launcher | Purpose | Working directory |
| --- | --- | --- |
| `guix-terminal-jail` | Interactive Bash shell | `/workspace` |
| `guix-agent-jail` | Run a locked uv Python application mounted read-only at `/app` | `/workspace` |
| `guix-codex-cli-jail` | Run Codex from host npm or a persistent standalone installation | `/workspaces/<project-id>` |

The Codex launcher **also mounts the selected project at `/workspace`** for
compatibility, but it starts Codex in the unique `/workspaces/<project-id>`
path.  This means new sessions from different projects can coexist in a
shared `~/.codex` without all having an identical recorded CWD of
`/workspace`. Sessions created outside the jail retain their original CWD
and may require `resume --all`.

**Start here:** [INSTALL.md](INSTALL.md) for first-time host setup,
[TESTING.md](TESTING.md) for regression and end-to-end verification.

## Quick start

After installing and configuring the host dependencies:

```bash
# Inspect the paths without starting Guix or mitmproxy.
guix-codex-cli-jail --paths ~/projects/my-project

# One-time per-project initialization, if using private credentials.
guix-codex-cli-jail --init ~/projects/my-project

# Launch Codex using the existing global npm installation.
guix-codex-cli-jail ~/projects/my-project

# Resume the most recent session whose saved CWD matches this project.
guix-codex-cli-jail ~/projects/my-project -- resume --last

# Existing entry points continue to work.
guix-terminal-jail ~/projects/my-project
guix-agent-jail --app ~/bin/myagent ~/projects/my-project -- --help
```

Host Codex discovery supports a global npm entry such as:

```text
/usr/local/bin/codex ->
  /usr/local/lib/node_modules/@openai/codex/bin/codex.js
```

It resolves this file and mounts **only** the `@openai/codex` package and any
separately located platform-native package read-only. The container uses Guix
Node.js to invoke the entrypoint. The host npm installation is **not** copied,
updated, or modified by the launcher. Continue updating it on the host with
`sudo npm install -g @openai/codex` if that is your chosen update workflow.

## Commands

### `guix-terminal-jail`

```text
guix-terminal-jail [options] [project_dir]
```

Opens an interactive shell at `/workspace`. The project defaults to the host
current directory. Options: `--paths`, `--init`, repeatable
`--add-package PACKAGE`, `-m MITM_ADDON`, `-p PNPM_DIR`, and `-h`.

### `guix-agent-jail`

```text
guix-agent-jail [options] [workspace_dir] [-- agent_args...]
```

Runs an existing Python application with a `pyproject.toml`, `uv.lock`, and
Python entry script. Choose the application with `-a DIR` / `--app DIR` or
`GUIX_AGENT_APP_DIR`; select the agent start-up script with `-e FILE` /
`--entry FILE` (default: `main.py`). The application path cannot overlap
the workspace.

Application source is mounted read-only at `/app`. A per-application,
per-project writable copy and virtual environment live at `/agent-state`.
The launcher locks that state, stages source, runs `uv sync --frozen
--no-editable`, then `uv run --frozen --no-sync` to execute the entry.
The default working directory remains `/workspace`. Its other options are
`--paths`, `--init`, repeatable `--add-package`, `-m`, `-p`, and `-h`.

### `guix-codex-cli-jail`

```text
guix-codex-cli-jail [options] [project_dir] [-- codex_args...]
```

| Option | Meaning |
| --- | --- |
| `project_dir` | Host project directory; default current directory |
| `--paths` | Show project/config/state, Codex paths and backend; no files created |
| `--init` | Create missing project-specific credentials; preserves existing credentials |
| `--backend host` | Reuse host global npm package read-only (**default**) |
| `--backend standalone` | Reuse persistent Guix-installed standalone executable |
| `--update` | Install/update **standalone** backend; implies standalone unless backend explicitly set |
| `--add-package PACKAGE` | Add another Guix package for this invocation; repeatable |
| `-m PATH`, `-p DIR` | Override proxy addon or host pnpm location |
| `-h`, `--help` | Help |

Use `--` to separate launcher options from Codex options:

```bash
guix-codex-cli-jail ~/projects/app -- --version
guix-codex-cli-jail ~/projects/app -- login status
guix-codex-cli-jail ~/projects/app -- resume --last
guix-codex-cli-jail ~/projects/app -- resume --all
```

`GUIX_CODEX_BACKEND=standalone` changes the default backend. For a non-standard
host npm executable path, set `GUIX_CODEX_HOST_ENTRY` to the full path of the
installed `codex.js` or its symlink; it must resolve to an
`@openai/codex/bin/codex.js` npm installation. Both `x86_64` and `aarch64`
Linux native dependency layouts are supported, including dependencies nested
inside the Codex package or located in a sibling `@openai` package directory.
Unsupported/missing native packages are reported before starting Guix.

#### Persistent standalone alternative

If the host npm binary cannot run inside Guix, or you prefer separate updates:

```bash
# Uses the official downloaded installer inside a Guix container.
# No host npm installation is required for this command.
guix-codex-cli-jail --update

# Reuse that installation without downloading it again.
guix-codex-cli-jail --backend standalone ~/projects/app

# Update again, explicitly, when desired.
guix-codex-cli-jail --update
```

The installer writes under `$XDG_STATE_HOME/guix-terminal/codex-cli/` (i.e.
`~/.local/state/guix-terminal/codex-cli/`). It stores an executable link in
`bin/` and release files in `store/packages/standalone/`. A single installation
is reused across projects. **`--update` never updates the host npm package.**

During an update, the launcher deliberately does not mount the selected
project or the shared `~/.codex` directory into the container. It still uses
the selected project's proxy and temporary container home. The downloaded
installer is remote executable code: review the installer and use this option
only if you trust the source. No installer is run on ordinary launches.

## Session history and paths

For each canonical host project path, the common launcher computes a stable
`<sanitized-name>-<12-character-hash>` ID. For example:

```text
Host:       ~/projects/api-service
Terminal:   /workspace
Codex CWD:  /workspaces/api-service-abcdef012345
CODEX_HOME: ~/.codex (shared read/write with host)
```

Only the selected project is exposed in each container; distinct projects have
different IDs. `resume --last` uses Codex's CWD filtering for new sessions.
The `--all` selector can display sessions created elsewhere, including on the
host. Resuming older host sessions does **not** magically translate their
stored absolute paths. Do not depend on arbitrary absolute `/workspace` paths
in prompts, stored commands, or AGENTS.md content if they must also work when
resumed from another project or on the host.

**Security implication:** Sharing `~/.codex` read/write exposes Codex's saved
session and authentication data (including any file-based tokens) to processes
inside the Codex container. This is a deliberate exception to the usual
proxy-only API-key model. Do not use this mode with untrusted processes or
assume Codex's own sandbox can protect secrets mounted into its container.
The script unsets the common `OPENAI_API_KEY=dummy_key` before launching Codex,
allowing its saved ChatGPT login to be used. Keychain-only host login may not be
available from inside the container; file-based login should be checked on
your machine using `-- login status`.

## Package selection

The package definitions are in [`lib/packages.sh`](lib/packages.sh), separate
from the shared container execution code. Change one profile without changing
the others:

| Profile | Package variable | Initial packages |
| --- | --- | --- |
| All launchers | `BASE_GUIX_PACKAGES` | `bash coreutils git findutils ncurses nss-certs less curl cmp grep zlib sed util-linux nano tar gzip gawk` |
| Interactive shell | `TERMINAL_GUIX_PACKAGES` | `gcc-toolchain uv python node` |
| Python agent | `AGENT_GUIX_PACKAGES` | `gcc-toolchain uv python node` |
| Host npm Codex | `CODEX_HOST_GUIX_PACKAGES` | `node` |
| Standalone Codex | `CODEX_STANDALONE_GUIX_PACKAGES` | Empty |

`tar`, `gzip`, and `gawk` remain in the base group by design. All launchers
also accept `--add-package PACKAGE` on a per-run basis. Guix package versions
follow your configured Guix channels; this repository does not pin channels.

## Credentials, proxy and state

The shared configuration root is `${XDG_CONFIG_HOME:-$HOME/.config}/guix-terminal`
and state is `${XDG_STATE_HOME:-$HOME/.local/state}/guix-terminal`.

| Resource | Location | Behavior |
| --- | --- | --- |
| Shared credentials | `config/guix-terminal/credentials.env` | Read by host-side proxy |
| Per-project credentials | `config/guix-terminal/projects/<id>/credentials.env` | If present, replaces shared credentials for that project |
| Per-project proxy log | `state/guix-terminal/projects/<id>/mitmdump.log` | Append-only timestamps and port information |
| Project temporary home | `state/guix-terminal/projects/<id>/home` | Removed after last session exits; supported history files retained |
| Python agent state | `state/guix-terminal/projects/<id>/apps/<app-hash>` | Persistent staged source + uv virtual environment |
| Standalone Codex binaries | `state/guix-terminal/codex-cli` | Persistent, shared across projects |
| Codex sessions and login | `~/.codex` | Host and Codex jail share it read/write |

`--paths` does not initialize state, start a proxy, or require Guix. `--init`
creates a project credentials file from `.env.example` only if missing; repeat
calls preserve the file. By default, only a selected set of provider endpoints
receives credentials injected by the host mitmproxy addon. Environment and
proxy templates live in `environment.sh`, `bashrc`, `key-injector.toml`, and
`inject_keys.py`. For project-specific overrides, install files under the
printed configuration root as described in INSTALL.md.

Each workspace's running sessions share one proxy and temporary home, with a
client registry and lock to manage concurrency. On the final session exit,
that proxy is stopped and supported shell histories are preserved. `HUP`,
`INT`, and `TERM` are forwarded to the container process tree. A crash or a
host reboot may leave state requiring manual cleanup.

## Filesystem and network boundaries

The common container uses `guix shell --container --emulate-fhs --network
--no-cwd`. Its standard mounts are the selected project (`/workspace`), a
project-specific temporary home, uv caches, mitmproxy's **public CA
certificate only**, the read-only `lib/` scripts, and the optional read-only
pnpm directory. Additional mounts depend on the launcher:

| Launcher | Additional mounts |
| --- | --- |
| Agent | Read-only `/app` source and writable `/agent-state` |
| Codex host | Read-only Codex npm package(s), `/workspaces/<id>` project alias, writable `~/.codex` |
| Codex standalone | Writable standalone installation, `/workspaces/<id>` alias, writable `~/.codex` |
| Standalone updater | Writable standalone installation only (no project and no `~/.codex`) |

Mount validation forbids exposing host `~/.config`, its configured XDG
configuration counterpart, or their ancestors, including the entire home.
Mount inputs containing the Guix mapping delimiter `=` are rejected. A
symlinked host `~/.codex` is rejected by the new launcher.

**Isolation is limited.** Containers have network access; environment proxy
variables do not force traffic through the proxy, prevent outbound connections,
or block host-loopback services. Shared mounts and same-user host processes
are not isolated from one another. The proxy injector is not a network
allowlist. Codex's additional sandbox may be unavailable inside the nested
Guix container; do not use `--dangerously-bypass-approvals-and-sandbox` as a
substitute for testing permissions. The new Codex integration is not a
security guarantee that code cannot access its deliberately mounted files.

## Troubleshooting

- **Missing proxy credentials:** use `--paths`, then `--init`, or create shared
  credentials per INSTALL.md; there is no implicit import of host environment
  `HOST_*` variables.
- **Proxy won't start:** inspect the selected project's `mitmdump.log`. The
  launcher tries ports 8080–8089 on `127.0.0.1`.
- **Missing Codex native dependency:** confirm `npm ls -g @openai/codex` and
  inspect the package's nested `node_modules/@openai` directory. The launcher
  does not expose all of `/usr/local` to hide a broken package structure.
- **Not logged into Codex:** verify `codex login status` on the host, then
  `guix-codex-cli-jail PROJECT -- login status`. File-based auth can work;
  host OS keychain integration may not be available inside Guix.
- **`resume --last` sees no sessions:** use `-- resume --all` to inspect
  sessions from different directories. New jail sessions should be scoped to
  `/workspaces/<id>`.
- **Codex TLS failures:** check your mitmproxy CA, the combined CA bundle in
  `environment.sh`, and the network/proxy behavior of the Codex binary.
- **Nested sandbox errors:** test with a disposable project; nested namespace
  and Bubblewrap support depends on your Guix/kernel setup. Do not silently
  weaken approval controls.
- **`--update` doesn't change host `codex --version`:** expected; it updates
  only the persistent standalone backend.
- **A launcher fails after a package update:** close active sessions and verify
  the host npm package layout and native dependency before restarting.

Run the offline regression suite using:

```bash
python3 -m unittest discover -s tests -v
```

See [TESTING.md](TESTING.md) for complete host acceptance tests and expected
limitations of offline checks.
