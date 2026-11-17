# Guix Terminal Jail

Run an interactive shell or a Python agent in a GNU Guix container,
with a writable workspace and a host-side mitmproxy addon that
supplies API credentials to selected HTTPS destinations.

**Author:** Steven J Holtz

The project provides two entry points:

- `guix-terminal-jail` opens Bash at `/workspace`.
- `guix-agent-jail` runs a uv-managed Python application mounted
  read-only at `/app`, with `/workspace` as its working directory.

Both launchers share the same workspace proxy, temporary container
home, credential selection, logging, and cleanup code.

## Dependencies

The host must run Linux with `/proc` and support `guix shell
--container --emulate-fhs --network`. Install and configure [GNU
Guix](https://guix.gnu.org/), including its daemon and permissions for
container use, before launching a jail.

Required host tools:

| Dependency | Purpose |
| --- | --- |
| Bash | Launchers and shared shell code |
| GNU Guix | Container construction and runtime packages |
| Python 3.11+ | Project setup, logging, and TOML parsing |
| mitmproxy (`mitmdump`) with Python 3.11+ and `python-dotenv` | Host-side HTTPS proxy and credential injection |
| GNU coreutils, `awk`, `sed`, `tr` | Paths, hashing, state files, and templates |
| `ss` (usually iproute2), `flock` (util-linux), `ps` (procps) | Proxy readiness checks, locking, and process tracking |
| Git | Cloning this repository |

The instructions below use host-side `uv` to install mitmproxy with
its addon dependency in the same Python environment. Another
installation works if `mitmdump` can import `dotenv` and `tomllib`.

The container receives these packages through Guix automatically:

```text
gcc-toolchain uv python bash coreutils git findutils ncurses
nss-certs less curl cmp grep zlib node sed util-linux nano
```

The first launch will likely be slow as it may need to download or
build packages. Guix package versions are selected by the host's
configured channels; this project does not pin a channel revision.

## Installation

### 1. Keep the complete project together

```bash
git clone https://github.com/sjholtz/guix-terminal-jail.git
cd guix-terminal-jail
chmod +x guix-terminal-jail guix-agent-jail
mkdir -p "$HOME/.local/bin"
ln -s "$PWD/guix-terminal-jail" "$HOME/.local/bin/guix-terminal-jail"
ln -s "$PWD/guix-agent-jail" "$HOME/.local/bin/guix-agent-jail"
export PATH="$HOME/.local/bin:$PATH"
```

Add the PATH setting to your host shell configuration if
necessary. Both launchers resolve symlinks to find their supporting
files. Keep `lib/`, `inject_keys.py`, `environment.sh`, `bashrc`, and
`.env.example` beside them; copying only the executable scripts is
insufficient.

In this working tree, `lib/` is ignored by `.gitignore`, and several
runtime files (including `guix-agent-jail` and `environment.sh`) are
not yet tracked. A clone of the committed files alone will be
incomplete until those runtime files are included in the
repository. The installation requires the complete layout described
above.

### 2. Install the host proxy

With `uv` installed on the host:

```bash
uv tool install --python 3.11 --with python-dotenv mitmproxy
uv tool update-shell
```

Reload your shell configuration or open a new terminal if needed, then
check:

```bash
command -v guix python3 mitmdump ss flock ps
python3 --version
mitmdump --version
```

If you have multiple proxy installations, use `type -a mitmdump` to
check which one the launcher will run.

### 3. Install header mappings

Run this from the repository directory:

```bash
config_base="${XDG_CONFIG_HOME:-$HOME/.config}"
install -d -m 700 "$config_base/guix-terminal"
install -m 600 key-injector.toml "$config_base/guix-terminal/key-injector.toml"
```

Use an absolute `XDG_CONFIG_HOME` if setting it explicitly. Shell and
environment templates have bundled defaults and do not need to be
copied.

### 4. Configure credentials

Create your workspace directory, then initialize its private
credentials:

```bash
mkdir -p "$HOME/projects/my-workspace"
guix-terminal-jail --init "$HOME/projects/my-workspace"
```

`--init` prints the resolved paths and creates a project-specific
`credentials.env` from `.env.example` without overwriting an existing
file. Edit the **Project credentials** path printed by the command and
replace the placeholder values with the keys you need. Remove unused
placeholders or leave those variables empty.

Alternatively, install shared credentials from the repository
directory:

```bash
install -m 600 .env.example "$config_base/guix-terminal/credentials.env"
# Edit that file to supply your keys.
```

A project credentials file takes precedence over the shared file **as
a whole**; values are not merged. Running `--init` therefore switches
that workspace to its project-specific file, even if shared
credentials already exist.

Credentials are read from the selected file, not from exported
`HOST_*` variables. Dotenv interpolation is disabled. The old
parent-directory `.env.guix-terminal-jail` location is no longer read.

### 5. Start a jail

```bash
guix-terminal-jail "$HOME/projects/my-workspace"
```

On first use, mitmproxy generates its CA files under the host's
`~/.mitmproxy`. The launcher exposes only `mitmproxy-ca-cert.cer` to
the container. The environment template combines it with Guix's public
CA bundle.

## Interactive shell usage

```text
guix-terminal-jail [--paths | --init] [-h] [-m inject_keys_path] [-p pnpm_host_path] [project_dir]
```

| Option | Behavior |
| --- | --- |
| `project_dir` | Workspace directory; defaults to the current directory |
| `--paths` | Print paths without creating files or starting Guix/proxy processes |
| `--init` | Create missing project credentials and prepare project state, then print paths |
| `-m PATH` | Select a host mitmproxy addon; defaults to bundled `inject_keys.py` |
| `-p DIR` | Select a host pnpm directory; defaults to `~/.local/share/pnpm` |
| `-h`, `--help` | Show help |

For example:

```bash
cd "$HOME/projects/my-workspace"
guix-terminal-jail --paths
guix-terminal-jail
```

The `--paths` option will show you where important files are located
and how external paths are mapped internally.

Inside the shell, the workspace is `/workspace`. Run your normal
development commands there, such as `uv sync` or `uv run python
main.py`. Type `exit` to leave; the bundled Bash configuration ignores
Ctrl+D.

Opening another jail for the same canonical workspace path reuses the
same proxy and container home, so 2 or more terminals can be opened to
the same contained environment. Each launch still creates its own Guix
container. Separate workspaces use separate state and proxies.

If the selected pnpm directory exists, it is mounted read-only at
`/host-pnpm`, and `/host-pnpm/bin` is added to PATH. pnpm is optional
and is not installed by these scripts.

## Python agent usage

```text
guix-agent-jail [options] [workspace_dir] [-- agent_args...]
```

| Option | Behavior |
| --- | --- |
| `-a DIR`, `--app DIR` | Application directory; defaults to `GUIX_AGENT_APP_DIR` |
| `-e FILE`, `--entry FILE` | Python script relative to the application; defaults to `main.py` |
| `--paths`, `--init` | Same workspace actions as the terminal launcher; no application required |
| `-m PATH`, `-p DIR` | Same addon and pnpm settings as the terminal launcher |
| `-h`, `--help` | Show help |

The application needs `pyproject.toml` with `[project].name`, a
committed `uv.lock`, and the entry script. The application and
workspace must be separate: neither directory may contain the
other. The entry must resolve to a file inside the application
directory.

```bash
# Application code lives outside the writable workspace.
guix-agent-jail --app "$HOME/bin/myagent" "$HOME/projects/my-workspace"

# Select a different entry and pass arguments to it.
guix-agent-jail --app "$HOME/bin/myagent" --entry scripts/run.py \
  "$HOME/projects/my-workspace" -- --verbose

# Or configure a default application for this host shell.
export GUIX_AGENT_APP_DIR="$HOME/bin/myagent"
guix-agent-jail "$HOME/projects/my-workspace" -- --verbose
```

For each application/workspace pair, the launcher:

1. Mounts the application read-only at `/app` and persistent
   application state at `/agent-state`.
2. Acquires a lock for the entire setup and run. Concurrent runs of
   the same pair wait; different pairs have separate locks.
3. Stages a writable application copy under `/agent-state/source`,
   excluding `.venv` and `__pycache__`, for build backends that write
   metadata.
4. Runs `uv sync --frozen --no-editable` with the virtual environment
   at `/agent-state/venv`. Source changes refresh the copy and trigger
   reinstallation of local packages.
5. Runs `uv run --project /agent-state/source --frozen --no-sync
   python /app/<entry>` with the supplied arguments and `/workspace`
   as the working directory.

Application state survives normal shutdown. Python bytecode is
redirected to temporary container storage. Dependencies must work with
the container's available tools and mounts; host paths outside the
exposed directories are unavailable.

## Credential injection

The bundled mappings are:

| Exact destination host | Header | Credentials file variable |
| --- | --- | --- |
| `api.openai.com` | `Authorization: Bearer …` | `HOST_OPENAI_API_KEY` |
| `ollama.com` | `Authorization: Bearer …` | `HOST_OLLAMA_API_KEY` |
| `api.githubcopilot.com` | `Authorization: Bearer …` | `HOST_GITHUB_API_KEY` |
| `api.anthropic.com` | `x-api-key` | `HOST_ANTHROPIC_API_KEY` |
| `api.smith.langchain.com` | `x-api-key` | `HOST_LANGSMITH_API_KEY` |

Add `HOST_GITHUB_API_KEY` yourself if needed; it is not in
`.env.example`. The example also contains `HOST_GOOGLE_API_KEY`, but
there is no bundled Google mapping.

The injector only modifies HTTPS requests on port 443. Host matching
is exact after lowercasing and removing a trailing dot; subdomains do
not match automatically. A matching header is replaced or
added. Missing or empty keys produce a warning and leave the request
header unchanged.

Customize `key-injector.toml` using these two supported sections:

```toml
[[auth.headers]]
host = "api.openai.com"
environment_variable = "HOST_OPENAI_API_KEY"

[[x-api.headers]]
host = "api.anthropic.com"
environment_variable = "HOST_ANTHROPIC_API_KEY"
```

`auth` always supplies the `Bearer ` prefix; `x-api` supplies the raw
value. Set `KEY_INJECTOR_CONFIG` in the host environment or selected
credentials file to use another TOML file. The host environment takes
precedence. Use an absolute path for predictable resolution.

Credentials and mappings load when the proxy starts. Close all
sessions for the workspace and relaunch after editing them. An active
proxy rejects attempts to attach using a different addon,
credential-file path, or config override.

## Configuration, state, and logs

Absolute XDG base paths are honored. Unset or relative values fall
back to the following defaults:

```text
~/.config/guix-terminal/
  key-injector.toml
  credentials.env                  # optional shared credentials
  bashrc                           # optional interactive shell override
  environment.sh                   # optional environment override
  projects/<project-id>/
    project_path
    credentials.env                # optional project credentials

~/.local/state/guix-terminal/projects/<project-id>/
  project_path
  mitmdump.log
  workspace.lock
  mitmdump.pid / mitmdump.start / mitmdump.port / proxy_config
  clients/
  home/                            # exists while workspace sessions are active
  bash_history / lesshst / python_history
  apps/<application-hash>/          # persistent source copy, venv, and run lock
```

The project ID combines a sanitized directory name and the first 12
characters of the SHA-256 hash of its canonical absolute
path. Application state uses a hash of the application's canonical
path. Moving either directory changes its identity.

Use `--paths` to find the actual locations. `mitmdump.log` combines
timestamped launcher events and proxy stdout/stderr, including
injector messages. It replaces the old standalone `inject_keys.log`;
`KEY_INJECTOR_LOG` is not used by the current code. The log is
appended and is not automatically rotated.

Launchers use `umask 077`; existing files and directories are not
recursively reset to private permissions. Keep credentials, state, and
logs private.

On normal last-session exit, the launcher stops the workspace proxy,
copies supported histories into that workspace's state, and removes
the shared container home. Other home-directory changes are
discarded. Histories are per workspace; there is no global history
merge or deduplication. HUP, INT, and TERM are forwarded through the
container process tree before cleanup.

Idle legacy state under
`~/.config/guix-terminal/state/projects/<full-hash>` is migrated
during initialization or launch. Active legacy sessions must be closed
first. Conflicting legacy and current state causes an error for manual
resolution. Cross-filesystem migration retains the original as a
backup.

## Container environment and access

| Host resource | Container location | Access |
| --- | --- | --- |
| Selected workspace | `/workspace` | Read/write |
| Workspace's temporary home | Host user's home path inside container | Read/write |
| `~/.cache/uv`, `~/.local/share/uv` | Same paths inside container | Read/write, shared across workspaces |
| `~/.mitmproxy/mitmproxy-ca-cert.cer` | Same path inside container | Read-only |
| Bundled `lib/` | `/run/guix-jail` | Read-only |
| Optional host pnpm directory | `/host-pnpm` | Read-only |
| Agent application | `/app` | Read-only, agent launcher only |
| Application/workspace state | `/agent-state` | Read/write, agent launcher only |

The launchers reject mount sources that overlap the host's default or
configured configuration directory, including ancestors such as the
entire host home. Mount sources containing `=` are also rejected.

`environment.sh` configures lowercase and uppercase proxy variables,
localhost proxy exclusions, dummy OpenAI/Anthropic/Ollama/LangSmith
keys, and CA variables for Python, requests, curl, Git, and Node. Its
default LangSmith tracing setting is `false`. The bundled interactive
`bashrc` also sets proxy and CA variables and changes LangSmith
tracing to `true`, with project `lca-deepagents`. Customize both
templates if you need consistent interactive and agent settings. Both
support the launcher's `#PORT#` substitution.

## Isolation limits

The container limits filesystem access to Guix runtime resources and
the mounts described above. The bundled injector keeps its real
credential file on the host and supplies credentials at the proxy
boundary. Keep secrets out of the workspace, application source,
shared caches, pnpm directory, and custom container templates.

Networking is shared with the host through `--network`. Proxy
environment variables configure cooperative clients; they do **not**
enforce proxy use, block direct connections, or prevent access to host
loopback services. CA settings establish trust and do not enforce
traffic routing. Files readable in the container can be sent over the
network.

The default injector is not a request allowlist or spending control: a
process can make authenticated requests to mapped providers through
the proxy. Other local processes able to reach the loopback proxy may
also use it. Containers and caches are not isolated from other
sessions running as the same host user. Protect the host mitmproxy CA
private key; only its public certificate is mounted by the launcher.

`agent-guardrails.py` is a separate example addon with a route
allowlist and a 100-request budget per addon instance. Selecting it
with `-m` **replaces** credential injection; it is not enabled or
combined with the injector automatically, and it only sees traffic
sent through the proxy.

## Example Use

An example use would be executing your own custom coding agent
(located in the app directory, e.g. `~/bin/myagent`) on project code
that is located in the workspace path
(e.g. `"$HOME/projects/my-workspace"`). This provides the ability to
securely execute your custom agent on a subset of your filesystem and
have the confidence that that agent will not run over your important
files or exfiltrate your secrets.

## Troubleshooting

- **Missing credentials:** run `--paths`, then initialize project
  credentials with `--init` or install the shared
  file. Parent-directory dotenv files and exported `HOST_*` keys are
  not credential sources.
- **Proxy cannot start:** inspect the printed workspace log. The
  launcher tries only loopback ports **8080–8089** and verifies that
  the started process owns the listener. Check for occupied ports,
  addon import errors, and missing or invalid TOML.
- **`No module named dotenv`:** ensure the selected `mitmdump`
  installation includes `python-dotenv`, as shown above.
- **TLS errors:** check the host CA certificate and your
  `environment.sh`/`bashrc` overrides. Certificate-pinning clients may
  reject proxy interception.
- **API requests missing from the proxy log:** the client may ignore
  proxy environment variables. Configure its transport
  explicitly. Merely setting a CA bundle does not route traffic
  through the proxy.
- **Mount rejected:** choose a workspace/application outside host
  configuration directories. Do not select the entire host home as the
  workspace.
- **Agent appears to wait:** another run may hold the lock for that
  application/workspace pair.
- **Changes to credentials have no effect:** close every jail for the
  workspace so its proxy exits, then restart.

## Project files

The root launchers and `lib/` implement the current
runtime. `inject_keys.py` is the default host addon;
`key-injector.toml` supplies mappings; `.env.example` supplies the
credential template; `bashrc` and `environment.sh` configure container
sessions.

## License

See [LICENSE](LICENSE) for the GNU General Public License, version 3.
