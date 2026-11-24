#!/usr/bin/env bash
# Host-side Codex package and state preparation, sourced after jail-common.sh.
CODEX_CONTAINER_ROOT=/opt/guix-codex-install
CODEX_NPM_CONTAINER_ROOT=/opt/host-codex/node_modules/@openai
CODEX_HOST_HOME="$HOME/.codex"
CODEX_INSTALL_STATE="$STATE_DIR/codex-cli"

codex_paths() {
    printf 'Codex project CWD: /workspaces/%s\nCodex host home: %s\nCodex container home: %s/.codex\nCodex backend: %s\nStandalone install state: %s\n' \
        "$PROJECT_ID" "$CODEX_HOST_HOME" "$HOME" "$CODEX_BACKEND" "$CODEX_INSTALL_STATE"
}

# Run this only after the selected workspace was canonicalized. This is not
# needed by --paths or --init, which must continue working without Codex.
prepare_codex_home() {
    [[ $CODEX_HOST_HOME == "$HOME/.codex" ]] || die 'Unexpected Codex home.'
    # Do not create or expose ~/.config, the host home itself, or arbitrary
    # CODEX_HOME supplied by the host environment.
    check_mount_source "$CODEX_HOST_HOME"
    if [[ -L $CODEX_HOST_HOME ]]; then
        die "Refusing symlinked ~/.codex; use a real directory: $CODEX_HOST_HOME"
    fi
    [[ ! -e $CODEX_HOST_HOME || -d $CODEX_HOST_HOME ]] || die "Not a directory: $CODEX_HOST_HOME"
    if [[ $PROJECT_DIR == "$CODEX_HOST_HOME" || $PROJECT_DIR == "$CODEX_HOST_HOME/"* ]]; then
        die 'The project cannot be inside ~/.codex (authentication and session storage).'
    fi
    mkdir -p -- "$CODEX_HOST_HOME"
    check_mount_source "$CODEX_HOST_HOME"
}

# For the current npm package, codex.js resolves the platform-native package
# through Node's module resolution; it may be nested or in a sibling directory.
# Expose only the Codex package(s), never /usr/local or all global node_modules.
prepare_host_codex() {
    local resolved native name triple candidate sibling
    local entry=${GUIX_CODEX_HOST_ENTRY:-}
    if [[ -z $entry ]]; then entry=$(command -v codex || true); fi
    [[ -n $entry ]] || die 'Host Codex not found; install @openai/codex or select --backend standalone.'
    resolved=$(realpath -e -- "$entry") || die "Cannot resolve Codex entry: $entry"
    [[ $resolved == */@openai/codex/bin/codex.js && -f $resolved ]] ||
        die "Expected an npm @openai/codex/bin/codex.js entry; found $resolved"
    CODEX_HOST_PACKAGE=${resolved%/bin/codex.js}
    [[ -r $CODEX_HOST_PACKAGE/package.json ]] || die "Missing package.json: $CODEX_HOST_PACKAGE"
    check_mount_source "$CODEX_HOST_PACKAGE"

    case $(uname -m) in
        x86_64)
            name=codex-linux-x64
            triple=x86_64-unknown-linux-musl
            ;;
        aarch64 | arm64)
            name=codex-linux-arm64
            triple=aarch64-unknown-linux-musl
            ;;
        *) die "Unsupported Codex npm platform: $(uname -m)" ;;
    esac
    CODEX_NATIVE_MOUNT=''
    CODEX_NATIVE_TARGET=''
    candidate="$CODEX_HOST_PACKAGE/node_modules/@openai/$name"
    sibling="${CODEX_HOST_PACKAGE%/codex}/$name"
    if [[ -d $candidate ]]; then
        # The nested module is included in the main exposed package. Symlinks
        # escaping the package would not survive the read-only bind.
        native=$(realpath -e -- "$candidate")
        [[ $native == "$CODEX_HOST_PACKAGE/"* ]] ||
            die "Nested Codex native dependency escapes package root: $candidate"
    elif [[ -d $sibling ]]; then
        CODEX_NATIVE_MOUNT=$(realpath -e -- "$sibling")
        CODEX_NATIVE_TARGET="$CODEX_NPM_CONTAINER_ROOT/$name"
        check_mount_source "$CODEX_NATIVE_MOUNT"
        native=$CODEX_NATIVE_MOUNT
    elif [[ -x $CODEX_HOST_PACKAGE/vendor/$triple/bin/codex ]]; then
        native="$CODEX_HOST_PACKAGE/vendor"
    else
        die "Missing $name native dependency (or bundled vendor binary) in host npm installation."
    fi
    [[ -x $native/vendor/$triple/bin/codex || -x $CODEX_HOST_PACKAGE/vendor/$triple/bin/codex ]] ||
        die "Missing executable native Codex binary for $triple"
}

add_codex_mounts() {
    if [[ $CODEX_ACTION == update ]]; then
        # The remote installer must not see ~/.codex or project files.
        add_mount share "$CODEX_INSTALL_STATE" "$CODEX_CONTAINER_ROOT"
        return
    fi
    # /workspace stays available for compatibility, but Codex's CWD is unique
    # across projects when using a shared ~/.codex session index.
    add_mount share "$PROJECT_DIR" "/workspaces/$PROJECT_ID"
    add_mount share "$CODEX_HOST_HOME" "$HOME/.codex"
    if [[ $CODEX_BACKEND == host ]]; then
        add_mount expose "$CODEX_HOST_PACKAGE" "$CODEX_NPM_CONTAINER_ROOT/codex"
        if [[ -n $CODEX_NATIVE_MOUNT ]]; then
            add_mount expose "$CODEX_NATIVE_MOUNT" "$CODEX_NATIVE_TARGET"
        fi
    else
        add_mount share "$CODEX_INSTALL_STATE" "$CODEX_CONTAINER_ROOT"
    fi
}

prepare_standalone_codex() {
    check_mount_source "$CODEX_INSTALL_STATE"
    mkdir -p -- "$CODEX_INSTALL_STATE"
    if [[ $CODEX_ACTION != update && ! -e $CODEX_INSTALL_STATE/bin/codex && ! -L $CODEX_INSTALL_STATE/bin/codex ]]; then
        die 'Standalone Codex not installed; use guix-codex-cli-jail --update --backend standalone.'
    fi
}
