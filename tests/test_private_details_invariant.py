"""No tracked file names a contributor's machine.

The repository is public. Private network hostnames and local home-directory
paths identify a person and their machine, and mean nothing to anyone else.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from support.weaver_test import weaver_test

ROOT = Path(__file__).resolve().parents[1]

PRIVATE = {
    "Tailscale hostname": re.compile(r"[A-Za-z0-9-]+\.ts\.net\b"),
    "macOS home directory": re.compile(r"/Users/[A-Za-z]"),
    "Linux home directory": re.compile(r"/home/[a-z_][a-z0-9_-]*/"),
    "agent profile directory": re.compile(r"\.hermes[/\\]"),
}


def _tracked() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode()
    return [ROOT / name for name in listed.split("\0") if name]


def _text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


@weaver_test()
def test_tracked_files_are_listed():
    assert ROOT / "pyproject.toml" in _tracked()


@weaver_test()
def test_no_tracked_file_names_a_private_host_or_home_directory():
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{number}: {kind}"
        for path in _tracked()
        if (text := _text(path)) is not None
        for number, line in enumerate(text.splitlines(), 1)
        for kind, pattern in PRIVATE.items()
        if pattern.search(line)
    ]
    assert not offenders, "Remove private details from:\n" + "\n".join(offenders)
