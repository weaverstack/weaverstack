"""Every workspace configuration field survives resolution and command overrides.

The configuration sets a non-default value for each field, so a resolution path
that rebuilds a Workspace from a few fields and resets the rest is visible.
"""

from __future__ import annotations

import argparse
import sys
import types
from dataclasses import replace

import pytest
from support.weaver_test import weaver_test

from weaver.config import DEFAULT_FILE, load_workspace, resolve_workspace
from weaver.declaration.model import WeaverItemId
from weaver.errors import CommandError
from weaver.operations.workspace import operation_workspace
from weaver.workspaces import (
    BuildConcurrency,
    CatalogueRef,
    EnvironmentRef,
    ExecutionSettings,
    RunConcurrency,
    TargetDeclaration,
    Workspace,
)

FULL = """\
workspace: Sales Analytics
environment: Tools/Runtime
catalogue: Warehouse/Catalogue
mirror: Production/Warehouse/Catalogue
execution:
  build:
    warehouse_concurrency: 3
    spark_concurrency: 5
    onelake_concurrency: 9
    shortcut_concurrency: 1
  run:
    spark_concurrency: 6
    warehouse_concurrency: 2
targets:
  Lakehouse/Landing: Landing_Dev
  Warehouse/Curated:
    name: Curated_Dev
data_sources:
  Sales: Warehouse/Curated
catalogue_dashboard: Dashboard
"""

OTHER = """\
workspace: Somewhere Else
catalogue: Warehouse/Other
"""

EXPECTED = Workspace(
    workspace="Sales Analytics",
    environment=EnvironmentRef(workspace="Tools", name="Runtime"),
    catalogue="Warehouse/Catalogue",
    mirror=CatalogueRef(workspace="Production", name="Catalogue"),
    execution=ExecutionSettings(
        build=BuildConcurrency(
            warehouse_concurrency=3,
            spark_concurrency=5,
            onelake_concurrency=9,
            shortcut_concurrency=1,
        ),
        run=RunConcurrency(spark_concurrency=6, warehouse_concurrency=2),
    ),
    targets={
        WeaverItemId.parse("Lakehouse/Landing"): TargetDeclaration("Landing_Dev"),
        WeaverItemId.parse("Warehouse/Curated"): TargetDeclaration("Curated_Dev"),
    },
    data_sources={"Sales": "Warehouse/Curated"},
    catalogue_dashboard="Dashboard",
)


def _fields(workspace: Workspace) -> dict:
    """Comparable values; the mappings are read-only proxies."""

    return {
        "workspace": workspace.workspace,
        "environment": workspace.environment,
        "catalogue": workspace.catalogue,
        "mirror": workspace.mirror,
        "execution": workspace.execution,
        "targets": dict(workspace.targets),
        "data_sources": dict(workspace.data_sources),
        "catalogue_dashboard": workspace.catalogue_dashboard,
    }


def _session(workspace: Workspace):
    return types.SimpleNamespace(workspace=workspace)


@pytest.fixture
def full(tmp_path):
    path = tmp_path / "full.yml"
    path.write_text(FULL, encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / DEFAULT_FILE).write_text(FULL, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def no_notebook(monkeypatch):
    monkeypatch.delitem(sys.modules, "notebookutils", raising=False)


@pytest.fixture
def notebook(monkeypatch, tmp_path):
    """A Fabric notebook running in Sales Analytics, outside any project."""

    runtime = types.SimpleNamespace(
        context={"currentWorkspaceName": "Sales Analytics"}
    )
    module = types.ModuleType("notebookutils")
    module.runtime = runtime
    monkeypatch.setitem(sys.modules, "notebookutils", module)
    monkeypatch.chdir(tmp_path)


# --- reading a file ------------------------------------------------------------


@weaver_test()
def test_a_file_keeps_every_field(full):
    assert _fields(load_workspace(full)) == _fields(EXPECTED)


@weaver_test()
def test_a_discovered_file_keeps_every_field(project):
    assert _fields(resolve_workspace()) == _fields(EXPECTED)


@weaver_test()
def test_an_explicit_catalogue_and_environment_change_only_themselves(full):
    resolved = resolve_workspace(
        workspace_config=full, catalogue="Warehouse/Other", environment="Other"
    )

    assert _fields(resolved) == _fields(
        replace(EXPECTED, catalogue="Warehouse/Other", environment="Other")
    )


@weaver_test()
def test_an_explicit_workspace_beside_a_file_renames_and_keeps_the_rest(full):
    resolved = resolve_workspace(workspace="Renamed", workspace_config=full)

    assert _fields(resolved) == _fields(replace(EXPECTED, workspace="Renamed"))


@weaver_test()
def test_an_explicit_workspace_alone_reads_no_discovered_file(project):
    resolved = resolve_workspace(workspace="Sales Analytics")

    assert _fields(resolved) == _fields(Workspace(workspace="Sales Analytics"))


# --- an operation given a Session --------------------------------------------


@weaver_test()
def test_an_operation_inherits_the_whole_session_configuration(no_notebook):
    resolved = operation_workspace("load", session=_session(EXPECTED))

    assert resolved is EXPECTED


@weaver_test()
def test_an_operation_override_changes_only_itself(no_notebook):
    session = _session(EXPECTED)

    overridden = operation_workspace(
        "load",
        catalogue="Warehouse/Other",
        environment="Other",
        session=session,
    )
    following = operation_workspace("load", session=session)

    assert _fields(overridden) == _fields(
        replace(EXPECTED, catalogue="Warehouse/Other", environment="Other")
    )
    assert following is EXPECTED
    assert session.workspace is EXPECTED


@weaver_test()
def test_an_operation_naming_a_file_resolves_that_file_instead(no_notebook, tmp_path):
    other = tmp_path / "other.yml"
    other.write_text(OTHER, encoding="utf-8")

    resolved = operation_workspace(
        "load", workspace_config=other, session=_session(EXPECTED)
    )

    assert _fields(resolved) == _fields(
        Workspace(workspace="Somewhere Else", catalogue="Warehouse/Other")
    )


@weaver_test()
def test_an_operation_naming_another_workspace_drops_the_session_configuration(
    no_notebook, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    resolved = operation_workspace(
        "test",
        workspace="Somewhere Else",
        session=_session(EXPECTED),
        needs_catalogue=False,
    )

    assert _fields(resolved) == _fields(Workspace(workspace="Somewhere Else"))


# --- a Fabric notebook ---------------------------------------------------------


@weaver_test()
def test_a_notebook_supplies_only_its_workspace(notebook):
    resolved = operation_workspace("test", needs_catalogue=False)

    assert _fields(resolved) == _fields(Workspace(workspace="Sales Analytics"))


@weaver_test()
def test_a_notebook_does_not_invent_a_catalogue(notebook):
    with pytest.raises(CommandError, match="load needs a Weaver catalogue"):
        operation_workspace("load")


@weaver_test()
def test_a_project_beside_a_notebook_wins(notebook, tmp_path):
    (tmp_path / DEFAULT_FILE).write_text(FULL, encoding="utf-8")

    assert _fields(operation_workspace("load")) == _fields(EXPECTED)


# --- a CLI command inside `weaver session` or `weaver workflow` ---------------


def _command(**values) -> argparse.Namespace:
    defaults = {
        "workspace": None,
        "workspace_config": None,
        "catalogue": None,
        "environment": None,
        "session": _session(EXPECTED),
    }
    defaults.update(values)
    return argparse.Namespace(**defaults)


@weaver_test()
def test_a_command_override_inside_a_session_changes_only_itself(no_notebook):
    from weaver_cli.main import _resolve_workspace

    resolved = _resolve_workspace(_command(catalogue="Warehouse/Other"))

    assert _fields(resolved) == _fields(replace(EXPECTED, catalogue="Warehouse/Other"))


@weaver_test()
def test_a_command_file_naming_the_session_workspace_keeps_the_session_configuration(
    no_notebook, tmp_path
):
    """Only the file's workspace is read; its other settings are not applied."""

    from weaver_cli.main import _resolve_workspace

    same = tmp_path / "same.yml"
    same.write_text(
        "workspace: Sales Analytics\ncatalogue: Warehouse/Other\n", encoding="utf-8"
    )

    resolved = _resolve_workspace(_command(workspace_config=str(same)))

    assert resolved is EXPECTED


@weaver_test()
def test_a_command_naming_another_workspace_inside_a_session_is_refused(no_notebook):
    from weaver_cli.main import _resolve_workspace

    with pytest.raises(CommandError, match="Session workspace is 'Sales Analytics'"):
        _resolve_workspace(_command(workspace="Somewhere Else"))


# --- a run sent to Fabric ------------------------------------------------------


@weaver_test()
def test_a_run_sent_to_fabric_carries_the_settings_a_run_reads():
    from weaver.sessions.run_in_fabric import _workspace_literal
    from weaver.workspaces import (  # noqa: F401 - names the literal uses
        BuildConcurrency,
        ExecutionSettings,
        RunConcurrency,
        TargetDeclaration,
    )

    carried = eval(_workspace_literal(EXPECTED))  # noqa: S307 - our own literal

    assert carried.workspace == EXPECTED.workspace
    assert carried.catalogue == EXPECTED.catalogue
    assert carried.environment == EXPECTED.environment
    assert carried.execution == EXPECTED.execution
    assert dict(carried.targets) == dict(EXPECTED.targets)
