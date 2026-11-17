"""Every release has its own notes in `CHANGELOG.md`."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from support.weaver_test import weaver_test

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    source = ROOT / "tools" / f"{name}.py"
    spec = spec_from_file_location(f"weaver_tools_{name}", source)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_notes = _load("release_notes")


@weaver_test()
def test_declared_version_has_release_notes():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    assert release_notes.section(text, version)


@weaver_test()
def test_section_stops_at_the_next_version():
    text = "# Changelog\n\n## 1.1.0\n\nNew.\n\n### Fixed\n\n- A.\n\n## 1.0.0\n\nOld.\n"

    assert release_notes.section(text, "1.1.0") == "New.\n\n### Fixed\n\n- A."
    assert release_notes.section(text, "1.0.0") == "Old."


@weaver_test()
def test_a_version_prefix_is_not_its_section():
    text = "## 1.1.0\n\nNew.\n"

    with pytest.raises(release_notes.ReleaseNotesError, match="'## 1.1' section"):
        release_notes.section(text, "1.1")


@weaver_test()
def test_an_empty_section_is_refused():
    with pytest.raises(release_notes.ReleaseNotesError, match="empty"):
        release_notes.section("## 1.1.0\n\n## 1.0.0\n\nOld.\n", "1.1.0")
