# Installation and upgrade guide

This guide applies to `guix-terminal-jail`, `guix-agent-jail`, and the new
`guix-codex-cli-jail` using the files in this repository.

## 1. Prerequisites

Linux with a functional Guix daemon and `guix shell --container
--emulate-fhs --network`. Host commands: Bash, `python3` (3.11+), GNU
coreutils, `sha256sum`, `realpath`, `awk`, `sed`, `ss`, `flock`, `ps`, `guix`,
and `mitmdump` with `python-dotenv` available to its Python interpreter.
The host Codex backend additionally requires a working global npm Codex
installation; the standalone backend does not.

Example host proxy install using `uv`:

```bash
uv tool install --python 3.11 --with python-dotenv mitmproxy
uv tool update-shell
command -v guix python3 mitmdump ss flock ps
```

The project does not install the Guix daemon or mitmproxy itself.

## 2. Install all project files together

From the downloaded archive or a Git checkout:

```bash
cd ~/bin/guix-terminal-jail
chmod +x guix-terminal-jail guix-agent-jail guix-codex-cli-jail
mkdir -p "$HOME/.local/bin"
ln -sfn "$PWD/guix-terminal-jail" "$HOME/.local/bin/guix-terminal-jail"
ln -sfn "$PWD/guix-agent-jail" "$HOME/.local/bin/guix-agent-jail"
ln -sfn "$PWD/guix-codex-cli-jail" "$HOME/.local/bin/guix-codex-cli-jail"
export PATH="$HOME/.local/bin:$PATH"
```

Make the PATH addition persistent in your host shell configuration. Do not
copy only the executable scripts: they resolve the symlink to locate `lib/`,
`bashrc`, `environment.sh`, `.env.example`, and the proxy addon.

If your existing repository has a `.gitignore` entry that ignores `lib/`,
remove that entry or use `git add -f` for the new/updated source files.
The supplied archive includes a `.gitignore` that does not exclude `lib/`.

## 3. Configure the host proxy and credentials

Install default route/header configuration:

```bash
config_base="${XDG_CONFIG_HOME:-$HOME/.config}"
install -d -m 700 "$config_base/guix-terminal"
install -m 600 key-injector.toml "$config_base/guix-terminal/key-injector.toml"
```

Then choose **one** credential arrangement:

```bash
# Shared across projects (edit this file after installation).
install -m 600 .env.example "$config_base/guix-terminal/credentials.env"
```

Or use private per-project credentials:

```bash
mkdir -p ~/projects/my-project
guix-terminal-jail --init ~/projects/my-project
# Edit the printed Project credentials path.
```

Private credentials override the shared file as a **whole file**, not by
merging individual keys. `--init` preserves credentials on repeated calls.
The Codex ChatGPT login is separate from mitmproxy's API-key mappings.

Make sure the host has run mitmproxy at least once so
`~/.mitmproxy/mitmproxy-ca-cert.cer` is present. The launcher mounts only this
public CA certificate; it does not mount the host mitmproxy private key.

## 4. Check your host npm Codex installation

The default new launcher reuses your global npm installation without copying
it or installing anything into Guix. Check:

```bash
command -v codex
readlink -f "$(command -v codex)"
npm root -g
codex --version
codex login status
```

The expected entrypoint looks like:

```text
/usr/local/lib/node_modules/@openai/codex/bin/codex.js
```

The launcher also discovers the required `@openai/codex-linux-x64` or
`@openai/codex-linux-arm64` native package either nested under
`@openai/codex/node_modules/@openai/` or in the sibling `@openai/` directory.
If your npm layout uses a different executable path, use
`GUIX_CODEX_HOST_ENTRY=/absolute/path/to/codex.js`; the entrypoint must still
resolve to a standard npm `@openai/codex/bin/codex.js` layout.

Update Codex **on the host** using your normal process:

```bash
sudo npm install -g @openai/codex
```

Do not update the global npm tree while a host-backed Codex jail is running:
the read-only bind points to files that npm may replace or remove.

## 5. Launch and validate Codex

```bash
guix-codex-cli-jail --paths ~/projects/my-project
guix-codex-cli-jail ~/projects/my-project -- --version
guix-codex-cli-jail ~/projects/my-project -- login status
guix-codex-cli-jail ~/projects/my-project
```

Interactive Codex uses the shared host `~/.codex` directory, mounted read/write,
for ChatGPT authentication, configuration, and session history. The launcher
unsets the dummy API key used by the common environment. The Codex UI should
start at `/workspaces/<project-id>`, **not** `/workspace`. If your host uses
OS keychain-only login, sharing files alone might not authenticate the jail.

Resume a previously created jail session:

```bash
guix-codex-cli-jail ~/projects/my-project -- resume --last
```

`resume --all` is useful for browsing earlier host or different-project
sessions, but their stored paths are not remapped automatically.

## 6. Optional persistent standalone Codex installation

If the npm-backed approach cannot run inside Guix:

```bash
# Explicit download and installation; never runs on a normal launch.
guix-codex-cli-jail --update

# Launch without touching npm or redownloading.
guix-codex-cli-jail --backend standalone ~/projects/my-project

# Future updates are explicit.
guix-codex-cli-jail --update
```

The standalone release files live under
`${XDG_STATE_HOME:-$HOME/.local/state}/guix-terminal/codex-cli/`. The official
installer is retrieved from `https://chatgpt.com/codex/install.sh` using
`curl -fsSL` and executed by `sh` inside the jail. The installer may change
in the future; inspect it before trusting it. The updater is intentionally
not given the project's `/workspace` or the host's `~/.codex` directory.
It still uses Guix-provided packages and the project-specific proxy.

To default future Codex launches to the standalone binary, set on the host:

```bash
export GUIX_CODEX_BACKEND=standalone
```

## 7. Keep the existing launchers working

```bash
guix-terminal-jail --paths ~/projects/my-project
guix-terminal-jail ~/projects/my-project

guix-agent-jail --paths ~/projects/my-project
guix-agent-jail --app ~/bin/myagent ~/projects/my-project -- --help
```

Package grouping is defined in `lib/packages.sh`. The original terminal and
agent package union remains available, and `tar`, `gzip`, `gawk` are retained
in the shared group. Change `TERMINAL_GUIX_PACKAGES`,
`AGENT_GUIX_PACKAGES`, `CODEX_HOST_GUIX_PACKAGES`, and
`CODEX_STANDALONE_GUIX_PACKAGES` independently.

## 8. Test before using a sensitive project

Run `python3 -m unittest discover -s tests -v`, then follow the disposable
workspace acceptance procedure in [TESTING.md](TESTING.md).

**Security note:** Codex can read and change the mounted project and shared
`~/.codex` contents. It is not equivalent to the original API-key-only proxy
model. The outer Guix container has network access, and nested Codex sandbox
support must be tested on your system. Never use `--dangerously-bypass-approvals-and-sandbox`
as a default launcher option.
