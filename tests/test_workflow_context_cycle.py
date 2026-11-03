"""`weaver.workflow()`: one Session, one configuration and one workflow ID."""

from __future__ import annotations

import sys
import threading
import types
from dataclasses import replace

import pytest
from support.weaver_test import weaver_test
from test_workspace_configuration_contract_declaration import EXPECTED, FULL, _fields

import weaver
from weaver.config import DEFAULT_FILE
from weaver.declaration.model import WeaverItemId
from weaver.errors import CommandError, ConfigError
from weaver.operations.workspace import operation_workspace
from weaver.run.record import open_run_record
from weaver.sessions.host import use_or_create_session
from weaver.sessions.testing import TestSession
from weaver.workflow import active_workflow
from weaver.workspaces import (
    ExecutionSettings,
    RunConcurrency,
    TargetDeclaration,
    Workspace,
)


@pytest.fixture
def opened(monkeypatch):
    """Sessions the workflow opens, as TestSessions."""

    created = []

    def session_for(workspace, **kwargs):
        session = TestSession(workspace=workspace)
        created.append((session, kwargs))
        return session

    monkeypatch.setattr("weaver.sessions.host.session_for", session_for)
    monkeypatch.delitem(sys.modules, "notebookutils", raising=False)
    return created


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / DEFAULT_FILE).write_text(FULL, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def full(tmp_path):
    path = tmp_path / "full.yml"
    path.write_text(FULL, encoding="utf-8")
    return path


# --- ownership -----------------------------------------------------------------


@weaver_test()
def test_a_workflow_opens_a_session_and_closes_it(opened, project):
    with weaver.workflow() as entered:
        session = entered.session
        assert not session.closed

    assert [each for each, _ in opened] == [session]
    assert session.closed


@weaver_test()
def test_an_opened_session_closes_after_an_error(opened, project):
    with pytest.raises(RuntimeError):
        with weaver.workflow() as entered:
            raise RuntimeError("inside")

    assert entered.session.closed
    assert active_workflow() is None


@weaver_test()
def test_a_given_session_is_borrowed_and_left_open(opened):
    session = TestSession(workspace=EXPECTED)

    with weaver.workflow(session=session) as entered:
        assert entered.session is session

    assert opened == []
    assert not session.closed


@weaver_test()
def test_a_closed_session_is_refused(opened):
    session = TestSession(workspace=EXPECTED)
    session.close()

    with pytest.raises(CommandError, match="closed"):
        with weaver.workflow(session=session):
            pass


@weaver_test()
def test_a_credential_reaches_only_a_session_the_workflow_opens(opened, project):
    credential = object()

    with weaver.workflow(credential=credential):
        pass
    with pytest.raises(CommandError, match="credential"):
        with weaver.workflow(session=TestSession(workspace=EXPECTED), credential=1):
            pass

    assert opened[0][1] == {"credential": credential}


@weaver_test()
def test_an_operation_inside_runs_on_the_workflows_session(opened):
    session = TestSession(workspace=EXPECTED)

    with weaver.workflow(session=session):
        with use_or_create_session(None) as used:
            assert used is session

    assert not session.closed
    assert opened == []


@weaver_test()
def test_an_operation_given_its_own_session_keeps_it(opened):
    workflow_session = TestSession(workspace=EXPECTED)
    other = TestSession(workspace=Workspace(workspace="Somewhere Else"))

    with weaver.workflow(session=workflow_session):
        with use_or_create_session(other) as used:
            assert used is other
        assert (
            operation_workspace("test", session=other, needs_catalogue=False)
            is other.workspace
        )


@weaver_test()
def test_a_notebook_session_leaves_the_notebooks_spark_running(monkeypatch, tmp_path):
    spark = types.SimpleNamespace(stopped=False)
    spark.stop = lambda: setattr(spark, "stopped", True)
    module = types.ModuleType("notebookutils")
    module.runtime = types.SimpleNamespace(
        context={"currentWorkspaceName": "Sales Analytics"}
    )
    monkeypatch.setitem(sys.modules, "notebookutils", module)
    monkeypatch.setattr("weaver.sessions.host.active_spark", lambda: spark)
    monkeypatch.chdir(tmp_path)

    from weaver.sessions.notebook import NotebookSession

    with weaver.workflow() as entered:
        assert isinstance(entered.session, NotebookSession)
        assert entered.session.spark() is spark

    assert entered.session.closed
    assert not spark.stopped


# --- configuration -------------------------------------------------------------


@weaver_test()
def test_a_workflow_inherits_the_whole_discovered_configuration(opened, project):
    with weaver.workflow() as entered:
        assert _fields(entered.workspace) == _fields(EXPECTED)
        assert operation_workspace("load") is entered.workspace


@weaver_test()
def test_a_workflow_inherits_a_given_sessions_whole_configuration(opened):
    with weaver.workflow(session=TestSession(workspace=EXPECTED)) as entered:
        assert entered.workspace is EXPECTED
        assert operation_workspace("load") is EXPECTED


@weaver_test()
def test_a_named_file_is_read_whole(opened, full):
    with weaver.workflow(workspace_config=full) as entered:
        assert _fields(entered.workspace) == _fields(EXPECTED)


@weaver_test()
def test_catalogue_and_environment_change_only_themselves(opened, full):
    with weaver.workflow(
        workspace_config=full, catalogue="Warehouse/Other", environment="Other"
    ) as entered:
        assert _fields(entered.workspace) == _fields(
            replace(EXPECTED, catalogue="Warehouse/Other", environment="Other")
        )


@weaver_test()
def test_structured_settings_change_only_the_entries_they_name(opened, full):
    with weaver.workflow(
        workspace_config=full,
        mirror="Staging/Warehouse/Catalogue",
        execution={"run": {"spark_concurrency": 8}},
        targets={"Lakehouse/Landing": "Landing_Test"},
        data_sources={"Inventory": "Lakehouse/Landing"},
        catalogue_dashboard="Dashboard_Test",
    ) as entered:
        resolved = entered.workspace

    assert _fields(resolved) == _fields(
        replace(
            EXPECTED,
            mirror=resolved.mirror,
            execution=replace(
                EXPECTED.execution,
                run=replace(EXPECTED.execution.run, spark_concurrency=8),
            ),
            targets={
                **EXPECTED.targets,
                WeaverItemId.parse("Lakehouse/Landing"): TargetDeclaration(
                    "Landing_Test"
                ),
            },
            data_sources={**EXPECTED.data_sources, "Inventory": "Lakehouse/Landing"},
            catalogue_dashboard="Dashboard_Test",
        )
    )
    assert str(resolved.mirror) == "Staging/Warehouse/Catalogue"


@weaver_test()
def test_a_build_setting_leaves_run_settings_and_other_build_settings(opened, full):
    with weaver.workflow(
        workspace_config=full, execution={"build": {"onelake_concurrency": 2}}
    ) as entered:
        execution = entered.workspace.execution

    assert execution.run == EXPECTED.execution.run
    assert execution.build == replace(EXPECTED.execution.build, onelake_concurrency=2)


@weaver_test()
def test_data_sources_accept_the_command_line_spelling(opened, full):
    with weaver.workflow(
        workspace_config=full, data_sources=["Sales=Lakehouse/Landing"]
    ) as entered:
        assert dict(entered.workspace.data_sources) == {"Sales": "Lakehouse/Landing"}


@weaver_test()
def test_empty_mappings_and_none_change_nothing(opened, full):
    with weaver.workflow(
        workspace_config=full,
        execution={},
        targets={},
        data_sources={},
        mirror=None,
    ) as entered:
        assert _fields(entered.workspace) == _fields(EXPECTED)


@weaver_test()
def test_an_override_leaves_the_inherited_workspace_unchanged(opened):
    with weaver.workflow(
        session=TestSession(workspace=EXPECTED),
        targets={"Lakehouse/Landing": "Landing_Test"},
        execution={"run": {"spark_concurrency": 8}},
    ) as entered:
        assert entered.workspace is not EXPECTED

    assert EXPECTED.targets[WeaverItemId.parse("Lakehouse/Landing")] == (
        TargetDeclaration("Landing_Dev")
    )
    assert EXPECTED.execution.run.spark_concurrency == 6


@weaver_test()
def test_typed_values_are_accepted(opened, full):
    settings = ExecutionSettings(run=RunConcurrency(warehouse_concurrency=1))
    targets = {WeaverItemId.parse("Warehouse/Curated"): TargetDeclaration("Curated_X")}

    with weaver.workflow(
        workspace_config=full, execution=settings, targets=targets
    ) as entered:
        # A typed ExecutionSettings is complete, so it is the whole value.
        assert entered.workspace.execution is settings
        assert dict(entered.workspace.targets) == {**EXPECTED.targets, **targets}


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"execution": {"run": {"spark_concurrency": 0}}}, "positive integer"),
        ({"execution": {"load": {}}}, "unknown keys: load"),
        ({"targets": {"Landing": "Landing_Dev"}}, "not an item identity"),
        ({"targets": ["Lakehouse/Landing"]}, "targets must be a mapping"),
        ({"data_sources": {"Sales": "Report/Sales"}}, "Warehouse/Name or Lakehouse"),
        ({"mirror": "Catalogue"}, "catalogue address"),
        ({"catalogue": "Lakehouse/Catalogue"}, "must name a Warehouse"),
        ({"catalogue_dashboard": " "}, "non-empty string"),
    ],
)
@weaver_test()
def test_an_invalid_override_is_refused_as_configuration(
    opened, full, overrides, message
):
    with pytest.raises(ConfigError, match=message):
        with weaver.workflow(workspace_config=full, **overrides):
            pass

    assert opened == []


@weaver_test()
def test_overrides_never_reach_the_given_session(opened):
    session = TestSession(workspace=EXPECTED)

    with weaver.workflow(session=session, catalogue="Warehouse/Other", targets={}):
        pass
    with weaver.workflow(session=session) as following:
        assert following.workspace is EXPECTED

    assert session.workspace is EXPECTED


@weaver_test()
def test_an_operation_override_is_local_to_that_operation(opened):
    with weaver.workflow(session=TestSession(workspace=EXPECTED)):
        overridden = operation_workspace("load", catalogue="Warehouse/Other")
        following = operation_workspace("load")

    assert overridden.catalogue == "Warehouse/Other"
    assert dict(overridden.targets) == dict(EXPECTED.targets)
    assert following is EXPECTED


@weaver_test()
def test_an_operation_naming_a_file_resolves_that_file(opened, tmp_path):
    other = tmp_path / "other.yml"
    other.write_text("workspace: Somewhere Else\n", encoding="utf-8")

    with weaver.workflow(session=TestSession(workspace=EXPECTED)):
        resolved = operation_workspace(
            "test", workspace_config=other, needs_catalogue=False
        )

    assert _fields(resolved) == _fields(Workspace(workspace="Somewhere Else"))


@weaver_test()
def test_a_notebook_workflow_has_its_workspace_and_no_invented_catalogue(
    monkeypatch, tmp_path
):
    module = types.ModuleType("notebookutils")
    module.runtime = types.SimpleNamespace(
        context={"currentWorkspaceName": "Sales Analytics"}
    )
    monkeypatch.setitem(sys.modules, "notebookutils", module)
    monkeypatch.setattr(
        "weaver.sessions.host.session_for",
        lambda workspace, **_: TestSession(workspace=workspace),
    )
    monkeypatch.chdir(tmp_path)

    with weaver.workflow() as entered:
        assert _fields(entered.workspace) == _fields(
            Workspace(workspace="Sales Analytics")
        )
        with pytest.raises(CommandError, match="load needs a Weaver catalogue"):
            operation_workspace("load")


@weaver_test()
def test_nothing_to_resolve_says_what_is_missing(opened, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(CommandError, match="workspace-config.yml"):
        with weaver.workflow():
            pass

    assert opened == []


@weaver_test()
def test_a_borrowed_session_without_a_workspace_resolves_nothing(opened, tmp_path):
    """A CLI workflow with no workspace configuration still runs."""

    session = TestSession(workspace=None)

    with weaver.workflow(session=session) as entered:
        assert entered.workspace is None


# --- workflow identity ---------------------------------------------------------


@weaver_test()
def test_runs_record_under_the_workflows_id(opened):
    session = TestSession(workspace=EXPECTED)

    with weaver.workflow(session=session) as entered:
        load = open_run_record(None, task_type="Load", session=session)
        test = open_run_record(None, task_type="Test", session=session)

    assert load.workflow_id == test.workflow_id == entered.workflow_id
    assert session.workflow_id is None


@weaver_test()
def test_successive_workflows_on_one_session_have_their_own_ids(opened):
    session = TestSession(workspace=EXPECTED)

    with weaver.workflow(session=session) as first:
        pass
    with weaver.workflow(session=session) as second:
        pass

    assert first.workflow_id != second.workflow_id
    assert open_run_record(None, task_type="Load", session=session).workflow_id not in (
        first.workflow_id,
        second.workflow_id,
    )


@weaver_test()
def test_a_nested_workflow_restores_the_outer_one_after_an_error(opened):
    session = TestSession(workspace=EXPECTED)

    with weaver.workflow(session=session) as outer:
        with pytest.raises(RuntimeError):
            with weaver.workflow(catalogue="Warehouse/Other") as inner:
                assert inner.session is session
                assert inner.workflow_id != outer.workflow_id
                assert session.workflow_id == inner.workflow_id
                assert operation_workspace("load").catalogue == "Warehouse/Other"
                raise RuntimeError("inside")
        assert active_workflow() is outer
        assert session.workflow_id == outer.workflow_id
        assert operation_workspace("load") is EXPECTED

    assert not session.closed
    assert opened == []


@weaver_test()
def test_a_nested_workflow_on_its_own_session_leaves_the_outer_session_alone(
    opened, project
):
    with weaver.workflow() as outer:
        inner_session = TestSession(workspace=Workspace(workspace="Somewhere Else"))
        with weaver.workflow(session=inner_session) as inner:
            assert outer.session.workflow_id == outer.workflow_id
            assert inner_session.workflow_id == inner.workflow_id
        assert not outer.session.closed

    assert not inner_session.closed
    assert outer.session.closed


@weaver_test()
def test_a_thread_started_inside_a_workflow_is_not_in_it(opened):
    seen = []

    with weaver.workflow(session=TestSession(workspace=EXPECTED)):
        thread = threading.Thread(target=lambda: seen.append(active_workflow()))
        thread.start()
        thread.join()

    assert seen == [None]


@weaver_test()
def test_one_session_runs_one_workflow_at_a_time_across_threads(opened):
    session = TestSession(workspace=EXPECTED)
    refused = []

    def concurrent():
        try:
            with weaver.workflow(session=session):
                pass
        except CommandError as exc:
            refused.append(str(exc))

    with weaver.workflow(session=session) as entered:
        thread = threading.Thread(target=concurrent)
        thread.start()
        thread.join()
        assert session.workflow_id == entered.workflow_id

    assert refused and "another thread" in refused[0]


@weaver_test()
def test_one_session_runs_one_workflow_at_a_time_across_asyncio_tasks(opened):
    import asyncio

    session = TestSession(workspace=EXPECTED)

    async def hold(entered: asyncio.Event, release: asyncio.Event):
        with weaver.workflow(session=session) as held:
            entered.set()
            await release.wait()
            return held.workflow_id, session.workflow_id

    async def overlap():
        with weaver.workflow(session=session):
            pass

    async def main():
        entered, release = asyncio.Event(), asyncio.Event()
        holder = asyncio.create_task(hold(entered, release))
        await entered.wait()
        with pytest.raises(CommandError, match="another thread or task"):
            await asyncio.create_task(overlap())
        release.set()
        held, during = await holder
        # Once the first workflow has ended, the Session takes another.
        await asyncio.create_task(overlap())
        return held, during

    held, during = asyncio.run(main())
    assert during == held
    assert session.workflow_id is None


@weaver_test()
def test_a_workflow_nests_within_one_asyncio_task(opened):
    import asyncio

    session = TestSession(workspace=EXPECTED)

    async def nested():
        with weaver.workflow(session=session) as outer:
            await asyncio.sleep(0)
            with pytest.raises(RuntimeError):
                with weaver.workflow(session=session) as inner:
                    assert session.workflow_id == inner.workflow_id
                    await asyncio.sleep(0)
                    raise RuntimeError
            return outer.workflow_id, session.workflow_id

    outer, restored = asyncio.run(nested())
    assert restored == outer
    assert session.workflow_id is None
