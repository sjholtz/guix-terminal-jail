# Compute paths without creating files or requiring Guix.
resolve_workspace() {
    local config_base=${XDG_CONFIG_HOME:-} state_base=${XDG_STATE_HOME:-} name
    [[ $config_base == /* ]] || config_base="$HOME/.config"
    [[ $state_base == /* ]] || state_base="$HOME/.local/state"
    CONFIG_BASE=$(realpath -m -- "$config_base")
    CONFIG_DIR="$CONFIG_BASE/guix-terminal"
    STATE_DIR="$(realpath -m -- "$state_base")/guix-terminal"
    PROJECT_DIR=$(realpath -e -- "$1")
    [[ -d $PROJECT_DIR ]] || die "Workspace is not a directory: $PROJECT_DIR"
    PROJECT_HASH=$(printf '%s' "$PROJECT_DIR" | sha256sum | awk '{print $1}')
    name=${PROJECT_DIR##*/}
    name=$(LC_ALL=C printf '%s' "${name:-root}" | LC_ALL=C tr -cs 'A-Za-z0-9._-' '_')
    PROJECT_ID="${name:0:100}-${PROJECT_HASH:0:12}"
    PROJECT_CONFIG_DIR="$CONFIG_DIR/projects/$PROJECT_ID"
    WORKSPACE_STATE_DIR="$STATE_DIR/projects/$PROJECT_ID"
    LEGACY_DIR="$HOME/.config/guix-terminal/state/projects/$PROJECT_HASH"
    PROXY_LOG="$WORKSPACE_STATE_DIR/mitmdump.log"
    PROJECT_ENV="$PROJECT_CONFIG_DIR/credentials.env"
    CREDENTIALS_FILE="$CONFIG_DIR/credentials.env"
    if [[ -e $PROJECT_ENV || -L $PROJECT_ENV ]]; then CREDENTIALS_FILE=$PROJECT_ENV; fi
    CLIENTS_DIR="$WORKSPACE_STATE_DIR/clients"
    CLIENT_FILE="$CLIENTS_DIR/$$"
    CONTAINER_HOME="$WORKSPACE_STATE_DIR/home"
    PID_FILE="$WORKSPACE_STATE_DIR/mitmdump.pid"
    PORT_FILE="$WORKSPACE_STATE_DIR/mitmdump.port"
    START_FILE="$WORKSPACE_STATE_DIR/mitmdump.start"
    PENDING_PID=""
}

show_paths() {
    printf 'Workspace: %s\nProject config: %s\nProject state: %s\nShared credentials: %s\nProject credentials: %s\nCredentials: %s\nLog: %s\n' \
        "$PROJECT_DIR" "$PROJECT_CONFIG_DIR" "$WORKSPACE_STATE_DIR" \
        "$CONFIG_DIR/credentials.env" "$PROJECT_ENV" "$CREDENTIALS_FILE" "$PROXY_LOG"
}

prepare_layout() {
    python3 "$JAIL_DIR/lib/prepare-project.py" "$1" "$PROJECT_DIR" "$PROJECT_CONFIG_DIR" \
        "$WORKSPACE_STATE_DIR" "$LEGACY_DIR" "$JAIL_DIR/.env.example"
}

# Shared by both commands; startup dependencies are checked only on a launch.
handle_workspace_action() {
    resolve_workspace "$1"
    case $ACTION in
        paths) show_paths; exit 0 ;;
        init) prepare_layout init; CREDENTIALS_FILE=$PROJECT_ENV; show_paths; exit 0 ;;
    esac
}

check_mount_source() {
    local path protected
    path=$(realpath -m -- "$1") || return 1
    for protected in "$HOME/.config" "$(realpath -m -- "$HOME/.config")" "$CONFIG_BASE"; do
        if [[ $path == / || $protected == / || $path == "$protected" ||
              $path == "$protected/"* || $protected == "$path/"* ]]; then
            die "Mount would expose host configuration: $path"
        fi
    done
    [[ $path != *'='* ]] || die "Guix mount source contains the mapping delimiter '=': $path"
}
