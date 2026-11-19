# Shared host-side implementation for both launchers.
# This file is sourced after the entry point sets JAIL_DIR and strict mode.
source "$JAIL_DIR/lib/project-layout.sh"
ACTION=run
MITM_SCRIPT="$JAIL_DIR/inject_keys.py"
PNPM_HOST_PATH="$HOME/.local/share/pnpm"
ADDITIONAL_PACKAGES=()
CONTAINER_PID=""

die() {
    echo "Error: $*" >&2
    exit 1
}

add_package() {
    [[ -n $1 && $1 != -* ]] || die "Expected a Guix package after --add-package."
    ADDITIONAL_PACKAGES+=("$1")
}

init_workspace() {
    local path
    for path in "$PROJECT_DIR" "$CONTAINER_HOME" "$HOME/.cache/uv" \
        "$HOME/.local/share/uv" "$HOME/.mitmproxy/mitmproxy-ca-cert.cer" "$JAIL_DIR/lib"; do
        check_mount_source "$path"
    done
    if [[ -d $PNPM_HOST_PATH ]]; then check_mount_source "$PNPM_HOST_PATH"; fi
    [[ -f $MITM_SCRIPT ]] || die "mitmproxy addon does not exist: $MITM_SCRIPT"
    MITM_SCRIPT=$(realpath -e -- "$MITM_SCRIPT")
    for program in python3 ss flock ps mitmdump guix; do
        command -v "$program" >/dev/null || die "Missing host command: $program"
    done
    prepare_layout run
    mkdir -p -- "$CLIENTS_DIR" "$HOME/.cache/uv" "$HOME/.local/share/uv" "$HOME/.mitmproxy"
}

log_event() {
    printf '%s [launcher] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S.%3N%:z')" "$*" >> "$PROXY_LOG"
}

# Field 22 is the Linux process start time. Remove PID and the parenthesized
# name first because the name can contain spaces. Ignore zombie processes.
process_start() {
    [[ $1 =~ ^[1-9][0-9]*$ ]] || return 1
    # From '/proc/pid/stat':
    #   - Remove the first 2 fields: Field 2 is the process name in parenthesis
    #   - If the 3rd field ($1 after removing 1st 2 fields) is 'Z' it is a zombie process
    #   - NF is the number of fields
    #   - print field 22 ($20 after removing 1st 2 fields)
    #
    # The process start time is "the time the process started after
    # system boot." (from docs: `man 5 proc_pid_stat`)
    awk '{sub(/^.*\) /,""); if ($1 != "Z" && NF >= 20) print $20; else exit 1}' \
        "/proc/$1/stat" 2>/dev/null
}

# True only if this PID owns the TCP listener at 127.0.0.1:port.
owns_proxy_port() {
    local pid=$1 port=$2 listeners
    [[ $pid =~ ^[1-9][0-9]*$ && $port =~ ^[0-9]{1,5}$ ]] || return 1
    listeners=$(ss -H -4 -ltnp "src 127.0.0.1 and sport = :$port") || return 1
    [[ $listeners == *"pid=$pid,"* ]]
}

# Set PROXY_PID, PROXY_START and PORT only from a verified workspace record.
load_proxy() {
    [[ -s $PID_FILE && -s $START_FILE && -s $PORT_FILE ]] || return 1
    PROXY_PID=$(<"$PID_FILE")
    PROXY_START=$(<"$START_FILE")
    PORT=$(<"$PORT_FILE")
    [[ $PROXY_START =~ ^[0-9]+$ ]] &&
        [[ $(process_start "$PROXY_PID") == "$PROXY_START" ]] &&
        owns_proxy_port "$PROXY_PID" "$PORT"
}

discard_candidate() {
    if [[ -n $PENDING_PID ]]; then
        kill "$PENDING_PID" 2>/dev/null || true
        wait "$PENDING_PID" 2>/dev/null || true
        PENDING_PID=""
    fi
}

ensure_mitmproxy() {
    local port start proxy_config
    proxy_config=$(printf '%s\0' "$MITM_SCRIPT" "$CONFIG_DIR" "$CREDENTIALS_FILE" \
        "${KEY_INJECTOR_CONFIG:-}" | sha256sum | awk '{print $1}')
    if load_proxy; then
        if [[ ! -f $WORKSPACE_STATE_DIR/proxy_config ||
              $(<"$WORKSPACE_STATE_DIR/proxy_config") != "$proxy_config" ]]; then
            die "The active workspace proxy uses a different credential file or addon. Close its sessions before switching settings."
        fi
        echo "Reusing mitmdump for '$PROJECT_DIR' (PID $PROXY_PID, port $PORT)." >&2
        return 0
    fi
    rm -f -- "$PID_FILE" "$START_FILE" "$PORT_FILE" "$WORKSPACE_STATE_DIR/proxy_config"

    if [[ $MITM_SCRIPT == "$JAIL_DIR/inject_keys.py" && ! -r $CREDENTIALS_FILE ]]; then
        die "Missing credentials: $CREDENTIALS_FILE. Install shared credentials or use --init for this workspace."
    fi
    for ((port=8080; port<8090; port++)); do
        log_event "trying 127.0.0.1:$port"
        # Close the inherited lock descriptor. exec makes $! the mitmdump PID.
        (
            # Remove the output file descriptor 9 for this subshell
            exec 9>&-
            cd -- "$PROJECT_DIR" || exit 1
            export GUIX_JAIL_CREDENTIALS="$CREDENTIALS_FILE" GUIX_JAIL_PROXY_PORT="$port"
            export GUIX_JAIL_CONFIG_DIR="$CONFIG_DIR" PYTHONUNBUFFERED=1
            exec > >(python3 "$JAIL_DIR/lib/proxy-log.py" "$port" >> "$PROXY_LOG" 2>&1) 2>&1
            exec mitmdump --listen-host 127.0.0.1 -s "$MITM_SCRIPT" -p "$port"
        ) &
        PENDING_PID=$!

        for _ in {1..50}; do
            kill -0 "$PENDING_PID" 2>/dev/null || break
            if owns_proxy_port "$PENDING_PID" "$port"; then
                start=$(process_start "$PENDING_PID") || break
                printf '%s\n' "$PENDING_PID" > "$PID_FILE"
                printf '%s\n' "$start" > "$START_FILE"
                printf '%s\n' "$port" > "$PORT_FILE"
                printf '%s\n' "$proxy_config" > "$WORKSPACE_STATE_DIR/proxy_config"
                log_event "listening on 127.0.0.1:$port pid=$PENDING_PID"
                PORT=$port
                echo "Started mitmdump for '$PROJECT_DIR' (PID $PENDING_PID, port $PORT)." >&2
                PENDING_PID=""
                return 0
            fi
            sleep 0.1
        done
        log_event "port $port failed readiness check (pid=$PENDING_PID)"
        discard_candidate
    done
    echo "Could not start a proxy on ports 8080–8089. See $PROXY_LOG" >&2
    return 1
}

cleanup() {
    local status=$? client pid started name remaining=0
    trap - EXIT
    trap '' HUP INT TERM
    flock -x 9 || exit 1
    discard_candidate
    rm -f -- "$CLIENT_FILE"

    for client in "$CLIENTS_DIR"/*; do
        [[ -f $client ]] || continue
        pid=${client##*/}
        started=$(process_start "$pid") || started=""
        # Older launchers used empty client files; keep a live legacy client.
        if [[ -n $started && ( ! -s $client || $(<"$client") == "$started" ) ]]; then
            remaining=1
        else
            rm -f -- "$client"
        fi
    done

    if (( remaining == 0 )); then
        if load_proxy; then
            kill "$PROXY_PID" 2>/dev/null || true
            # The last launcher may be a different terminal from its parent.
            for _ in {1..100}; do
                [[ $(process_start "$PROXY_PID") == "$PROXY_START" ]] || break
                sleep 0.1
            done
            if [[ $(process_start "$PROXY_PID") == "$PROXY_START" ]]; then
                echo "mitmdump PID $PROXY_PID is still exiting; keeping its state." >&2
                exit 1
            fi
            wait "$PROXY_PID" 2>/dev/null || true
            log_event "stopped port=$PORT pid=$PROXY_PID"
            echo "Stopped mitmdump for '$PROJECT_DIR' (PID $PROXY_PID)." >&2
        fi
        rm -f -- "$PID_FILE" "$START_FILE" "$PORT_FILE" "$WORKSPACE_STATE_DIR/proxy_config"

        if [[ -d $CONTAINER_HOME ]]; then
            for name in bash_history lesshst python_history; do
                if [[ -f $CONTAINER_HOME/.$name && ! -L $CONTAINER_HOME/.$name ]]; then
                    cp -- "$CONTAINER_HOME/.$name" "$WORKSPACE_STATE_DIR/$name"
                fi
            done
            rm -rf -- "$CONTAINER_HOME"
        fi
    fi
    exit "$status"
}

# Signal the container's descendants as well as its outer Guix process.
# Killing only a waiting supervisor can leave its Python child running.
signal_container_tree() {
    local pid=$1 signal=$2 started children="" child
    started=$(process_start "$pid") || return 0
    children=$(ps -o pid= --ppid "$pid" 2>/dev/null) || true
    # ps supplies whitespace-separated numeric PIDs.
    for child in $children; do
        signal_container_tree "$child" "$signal"
    done
    if [[ $(process_start "$pid") == "$started" ]]; then
        kill -s "$signal" "$pid" 2>/dev/null || true
    fi
}

# Bash handles these traps while waiting for the asynchronous Guix child.
# Wait for the container before releasing its proxy and shared home.
forward_signal() {
    local signal=$1 status=$2
    trap '' HUP INT TERM
    if [[ -n $CONTAINER_PID ]]; then
        signal_container_tree "$CONTAINER_PID" "$signal"
        wait "$CONTAINER_PID" 2>/dev/null || true
        CONTAINER_PID=""
    fi
    exit "$status"
}

start_workspace() {
    local name bashrc_template env_template
    # The lock covers registration, proxy selection and shared home setup.
    exec 9>"$WORKSPACE_STATE_DIR/workspace.lock"
    flock -x 9
    trap cleanup EXIT
    trap 'forward_signal HUP 129' HUP
    trap 'forward_signal INT 130' INT
    trap 'forward_signal TERM 143' TERM
    process_start "$$" > "$CLIENT_FILE"
    ensure_mitmproxy

    if [[ ! -d $CONTAINER_HOME ]]; then
        mkdir -p -- "$CONTAINER_HOME"
        for name in bash_history lesshst python_history; do
            if [[ -f $WORKSPACE_STATE_DIR/$name && ! -L $WORKSPACE_STATE_DIR/$name ]]; then
                cp -- "$WORKSPACE_STATE_DIR/$name" "$CONTAINER_HOME/.$name"
            fi
        done
    fi

    bashrc_template="$CONFIG_DIR/bashrc"
    [[ -f $bashrc_template ]] || bashrc_template="$JAIL_DIR/bashrc"
    env_template="$CONFIG_DIR/environment.sh"
    [[ -f $env_template ]] || env_template="$JAIL_DIR/environment.sh"
    render_template "$bashrc_template" "$CONTAINER_HOME/.bashrc"
    render_template "$env_template" "$CONTAINER_HOME/.guix-jail-env"
    flock -u 9
}

render_template() {
    local temporary
    temporary=$(mktemp -- "$CONTAINER_HOME/.template.XXXXXXXX")
    sed "s/#PORT#/$PORT/g" "$1" > "$temporary"
    mv -fT -- "$temporary" "$2"
}

build_guix_args() {
    GUIX_ARGS=(shell --container --emulate-fhs --network --no-cwd --preserve='^TERM$')
    add_mount share "$PROJECT_DIR" /workspace
    add_mount share "$CONTAINER_HOME" "$HOME"
    add_mount share "$HOME/.cache/uv" "$HOME/.cache/uv"
    add_mount share "$HOME/.local/share/uv" "$HOME/.local/share/uv"
    add_mount expose "$HOME/.mitmproxy/mitmproxy-ca-cert.cer" "$HOME/.mitmproxy/mitmproxy-ca-cert.cer"
    add_mount expose "$JAIL_DIR/lib" /run/guix-jail
    if [[ -d $PNPM_HOST_PATH ]]; then add_mount expose "$PNPM_HOST_PATH" /host-pnpm; fi
}

add_mount() {
    local source
    source=$(realpath -e -- "$2")
    check_mount_source "$source"
    GUIX_ARGS+=("--$1=$source=$3")
}

run_container() {
    local status=0
    # Retain the caller's stdin explicitly for the asynchronous child.
    # The parent owns the workspace lock descriptor; the child closes it.
    guix "${GUIX_ARGS[@]}" \
        gcc-toolchain uv python bash coreutils git findutils ncurses \
        nss-certs less curl cmp grep zlib node sed util-linux nano \
        "${ADDITIONAL_PACKAGES[@]}" -- "$@" <&0 9>&- &
    CONTAINER_PID=$!
    wait "$CONTAINER_PID" || status=$?
    CONTAINER_PID=""
    return "$status"
}
