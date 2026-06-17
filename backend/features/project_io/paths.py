"""Path fingerprinting and relinking helpers for project files."""

from __future__ import annotations

from pathlib import Path

from backend.features.project_io.schema import FileFingerprint


def fingerprint_file(path: Path) -> FileFingerprint:
    """Return a cheap (size, mtime) signature for an existing file.

    Missing files yield an empty fingerprint rather than raising, so a project
    can still be exported when a referenced file is temporarily absent.
    """
    try:
        stat = path.stat()
    except OSError:
        return FileFingerprint()
    return FileFingerprint(size=stat.st_size, mtime=stat.st_mtime)


def relative_to_cwd(path: Path) -> str | None:
    """Return ``path`` relative to the current working directory, if possible.

    The working directory is the app's repo root, under which ``temp/uploads``
    and ``temp/outputs`` live. Paths outside the tree return ``None``.
    """
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return None


def fingerprint_matches(path: Path, expected: FileFingerprint) -> bool:
    """Return whether ``path``'s size matches the saved fingerprint.

    Only size is compared — mtime legitimately changes on copy/move, so it is
    advisory. An empty expected fingerprint is treated as a match (unknown).
    """
    if expected.size is None:
        return True
    try:
        return path.stat().st_size == expected.size
    except OSError:
        return False


def resolve_reference(
    path_abs: str | None, path_rel: str | None
) -> Path | None:
    """Resolve a saved reference to an existing file on this machine.

    Tries the absolute path first, then the relative path against the current
    working directory. Returns the first that exists, else ``None``.
    """
    if path_abs:
        candidate = Path(path_abs)
        if candidate.exists():
            return candidate
    if path_rel:
        candidate = (Path.cwd() / path_rel).resolve()
        if candidate.exists():
            return candidate
    return None
