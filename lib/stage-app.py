"""Prepare a writable build tree. Caller must hold the application run lock."""

import hashlib
import os
import re
import shutil
import stat
import sys
from pathlib import Path

import tomllib


def ignored(directory, names):
    # Never copy a host virtual environment or generated Python bytecode.
    return {name for name in names if name in {".venv", "__pycache__"}}


def fingerprint(source):
    digest = hashlib.sha256()
    for directory, directories, files in os.walk(source, followlinks=False):
        directories[:] = sorted(set(directories) - ignored(directory, directories))
        files = sorted(set(files) - ignored(directory, files))
        for name in sorted(directories + files):
            path = Path(directory) / name
            info = path.lstat()
            digest.update(os.fsencode(path.relative_to(source)) + b"\0")
            digest.update(str(stat.S_IMODE(info.st_mode)).encode() + b"\0")
            if path.is_symlink():
                digest.update(b"link\0" + os.fsencode(os.readlink(path)) + b"\0")
            elif path.is_file():
                digest.update(b"file\0")
                with path.open("rb") as content:
                    for chunk in iter(lambda: content.read(1024 * 1024), b""):
                        digest.update(chunk)
                digest.update(b"\0")
            elif path.is_dir():
                digest.update(b"directory\0")
            else:
                raise ValueError(f"Unsupported application file type: {path}")
    return digest.hexdigest()


def stage(source, state):
    source_hash = fingerprint(source)
    target = state / "source"
    marker = state / "source-hash"
    if (
        not target.is_dir()
        or not marker.exists()
        or marker.read_text().strip() != source_hash
    ):
        temporary = state / "source.new"
        previous = state / "source.old"
        shutil.rmtree(temporary, ignore_errors=True)
        shutil.rmtree(previous, ignore_errors=True)
        shutil.copytree(source, temporary, symlinks=True, ignore=ignored)
        # A read-only host file mode should not prevent build metadata writes.
        for directory, directories, files in os.walk(temporary):
            for path in [Path(directory), *(Path(directory) / name for name in files)]:
                if not path.is_symlink():
                    path.chmod(path.stat().st_mode | stat.S_IWUSR)
        # Detect edits on the host during the copy before publishing a snapshot.
        if fingerprint(source) != source_hash:
            shutil.rmtree(temporary)
            raise RuntimeError(
                "Application changed during setup. Run the launcher again."
            )
        if target.exists():
            target.rename(previous)
        try:
            temporary.rename(target)
        except OSError:
            if previous.exists():
                previous.rename(target)
            raise
        shutil.rmtree(previous, ignore_errors=True)
        temporary_marker = state / "source-hash.new"
        temporary_marker.write_text(source_hash + "\n")
        temporary_marker.replace(marker)

    with (target / "pyproject.toml").open("rb") as metadata:
        package = tomllib.load(metadata)["project"]["name"]
    local_packages = {package}
    with (target / "uv.lock").open("rb") as lockfile:
        for locked in tomllib.load(lockfile).get("package", []):
            location = locked.get("source", {})
            if any(
                kind in location
                for kind in ("directory", "editable", "virtual", "path")
            ):
                local_packages.add(locked["name"])
    for name in local_packages:
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*", name
        ):
            raise ValueError("Application metadata contains an invalid package name")
    print(source_hash, *sorted(local_packages))


if __name__ == "__main__":
    stage(Path(sys.argv[1]), Path(sys.argv[2]))
