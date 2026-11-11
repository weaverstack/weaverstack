#!/usr/bin/env python3
"""Print one version's section of `CHANGELOG.md`."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


class ReleaseNotesError(Exception):
    """The changelog has no usable section for a version."""


def section(text: str, version: str) -> str:
    """The body under `## <version>`, up to the next second-level heading."""

    heading = re.compile(rf"^## {re.escape(version)}[ \t]*$", re.MULTILINE)
    found = heading.search(text)
    if found is None:
        raise ReleaseNotesError(f"CHANGELOG.md has no '## {version}' section.")
    following = re.compile(r"^## ", re.MULTILINE).search(text, found.end())
    body = text[found.end() : following.start() if following else len(text)]
    body = body.strip()
    if not body:
        raise ReleaseNotesError(f"CHANGELOG.md's '## {version}' section is empty.")
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        print(section(CHANGELOG.read_text(encoding="utf-8"), args.version))
    except ReleaseNotesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
