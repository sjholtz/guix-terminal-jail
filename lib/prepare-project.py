"""Provision a project, preserving idle legacy state and existing credentials."""

import errno
import fcntl
import os
import shutil
import sys
import tempfile
from pathlib import Path


def check_identity(directory, project):
    marker = directory / "project_path"
    if marker.exists() and marker.read_bytes() != os.fsencode(project) + b"\n":
        raise ValueError(f"Workspace identity differs in {directory}")


def create_once(path, data):
    # Publish a complete private file even if two different state
    # roots share config.
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        name = Path(temporary.name)
        try:
            temporary.write(data)
            temporary.flush()
            try:
                os.link(name, path)
            except FileExistsError:
                pass
        finally:
            name.unlink(missing_ok=True)


def living(pid, start):
    if not pid.isdecimal():
        return False
    try:
        fields = Path(f"/proc/{pid}/stat").read_bytes().rsplit(b") ", 1)[1].split()
    except (FileNotFoundError, ProcessLookupError):
        return False
    return fields[0] != b"Z" and (not start or fields[19] == start)


def migrate(old, new, project):
    check_identity(old, project)
    with (old / "workspace.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for client in (old / "clients").glob("*"):
            if living(client.name, client.read_bytes().strip()):
                raise ValueError(
                    f"Close the active legacy session for {project} and retry"
                )
        pid = old / "mitmdump.pid"
        start = old / "mitmdump.start"
        if pid.is_file() and living(
            pid.read_text().strip(),
            start.read_bytes().strip() if start.is_file() else b"",
        ):
            raise ValueError(
                f"Legacy proxy still active for {project}. Close that session and retry"
            )
        try:
            old.rename(new)
        except OSError as error:
            if error.errno != errno.EXDEV:
                raise
            # Publish only after a successful copy. Keep the original as a backup.
            with tempfile.TemporaryDirectory(dir=new.parent) as temp:
                staged = Path(temp) / "state"
                shutil.copytree(old, staged, symlinks=True)
                (staged / ".legacy-copy").write_bytes(os.fsencode(old))
                staged.rename(new)


def prepare(action, project, config, state, old, template):
    state.parent.mkdir(parents=True, exist_ok=True)
    with (state.parent / ".layout.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        check_identity(config, project)
        check_identity(state, project)
        if old.is_dir():
            if state.exists():
                marker = state / ".legacy-copy"
                if not marker.is_file() or marker.read_bytes() != os.fsencode(old):
                    raise ValueError(
                        f"Both legacy and new state exist: {old} and {state}. Resolve before launch"
                    )
            else:
                migrate(old, state, project)
        state.mkdir(exist_ok=True)
        create_once(state / "project_path", os.fsencode(project) + b"\n")
        check_identity(state, project)
        if action == "init":
            config.mkdir(parents=True, exist_ok=True)
            create_once(config / "project_path", os.fsencode(project) + b"\n")
            check_identity(config, project)
            create_once(config / "credentials.env", template.read_bytes())


if __name__ == "__main__":
    try:
        prepare(sys.argv[1], *(Path(value) for value in sys.argv[2:]))
    except (OSError, ValueError) as error:
        sys.exit(f"Cannot prepare project: {error}")
