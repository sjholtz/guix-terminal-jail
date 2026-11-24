#!/usr/bin/env bash
# Inside the Guix container: start Codex with stable per-project CWD.
set -euo pipefail
source "$HOME/.guix-jail-env"
backend=$1
project_id=$2
shift 2
[[ $project_id =~ ^[A-Za-z0-9._-]+$ ]] || {
    echo 'Invalid project ID' >&2
    exit 1
}
cd -- "/workspaces/$project_id"

# The common environment uses a proxy-injected dummy API key for other agents.
# With a shared ChatGPT login in ~/.codex, do not make Codex use that dummy key.
unset OPENAI_API_KEY
export CODEX_HOME="$HOME/.codex"
case $backend in
    host) exec node /opt/host-codex/node_modules/@openai/codex/bin/codex.js "$@" ;;
    standalone) exec /opt/guix-codex-install/bin/codex "$@" ;;
    *)
        echo "Unsupported Codex backend: $backend" >&2
        exit 1
        ;;
esac
