#!/usr/bin/env bash
# Executed inside the Guix container. The host launcher validates the entry.
set -euo pipefail
source "$HOME/.guix-jail-env"
cd /workspace
entry=$1
shift

export UV_PROJECT_ENVIRONMENT=/agent-state/venv
# Keep Python bytecode out of the read-only application mount.
export PYTHONPYCACHEPREFIX=/tmp/guix-agent-pycache

# Keep the lock for the full setup/agent lifetime. Mount the parent of venv
# so uv can recreate the directory when necessary. uv inherits descriptor 8.
exec 8>/agent-state/run.lock
flock -x 8

# Some build backends write metadata into the source tree. Give them a
# persistent working copy while keeping the original /app mount read-only.
snapshot=$(python3 /run/guix-jail/stage-app.py /app /agent-state)
read -ra snapshot_fields <<< "$snapshot"
source_hash=${snapshot_fields[0]}
sync_args=(--project /agent-state/source --frozen --no-editable)
if [[ ! -f /agent-state/synced-source || $(</agent-state/synced-source) != "$source_hash" ]]; then
    # uv normally watches project metadata. Rebuild the application itself
    # when source code changes, including files outside that default watch set.
    for package_name in "${snapshot_fields[@]:1}"; do
        sync_args+=(--reinstall-package "$package_name")
    done
fi
uv sync "${sync_args[@]}"
printf '%s\n' "$source_hash" > /agent-state/synced-source.new
mv -f /agent-state/synced-source.new /agent-state/synced-source

# The explicit sync above runs under the same lock as this command.
exec uv run --project /agent-state/source --frozen --no-sync \
    python "/app/$entry" "$@"
