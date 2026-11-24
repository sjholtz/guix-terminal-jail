#!/usr/bin/env bash
# Inside the Guix container: explicit, persistent standalone Codex update.
set -euo pipefail
source "$HOME/.guix-jail-env"
unset OPENAI_API_KEY
export CODEX_HOME=/opt/guix-codex-install/store
export CODEX_INSTALL_DIR=/opt/guix-codex-install/bin
export CODEX_NON_INTERACTIVE=1
umask 077
mkdir -p "$CODEX_HOME" "$CODEX_INSTALL_DIR"
installer=$(mktemp)
trap 'rm -f -- "$installer"' EXIT
# Deliberately download first rather than pipe unreviewed stream into sh.
# This is still remote executable code. See INSTALL.md for the trust model.
curl -fsSL https://chatgpt.com/codex/install.sh -o "$installer"
sh "$installer"
"$CODEX_INSTALL_DIR/codex" --version
