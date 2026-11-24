#!/usr/bin/env bash
# Guix package groups. Source from jail-common.sh; do not execute directly.
# Packages here are available to every launcher. Keep tar/gzip/gawk for useful
# shell development workflows and for the optional Codex standalone installer.
BASE_GUIX_PACKAGES=(
    bash coreutils git findutils ncurses nss-certs less curl cmp grep zlib
    sed util-linux nano tar gzip gawk
)

# Independently tunable package sets. --add-package remains per-invocation.
TERMINAL_GUIX_PACKAGES=(gcc-toolchain uv python node)
AGENT_GUIX_PACKAGES=(gcc-toolchain uv python node)
CODEX_HOST_GUIX_PACKAGES=(node procps)
CODEX_STANDALONE_GUIX_PACKAGES=(procps)

LAUNCHER_GUIX_PACKAGES=()
select_launcher_packages() {
    case $1 in
        terminal) LAUNCHER_GUIX_PACKAGES=("${TERMINAL_GUIX_PACKAGES[@]}") ;;
        agent) LAUNCHER_GUIX_PACKAGES=("${AGENT_GUIX_PACKAGES[@]}") ;;
        codex-host) LAUNCHER_GUIX_PACKAGES=("${CODEX_HOST_GUIX_PACKAGES[@]}") ;;
        codex-standalone) LAUNCHER_GUIX_PACKAGES=("${CODEX_STANDALONE_GUIX_PACKAGES[@]}") ;;
        *) die "Unknown Guix package profile: $1" ;;
    esac
}
