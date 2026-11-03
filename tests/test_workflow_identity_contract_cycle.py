"""A run records under the workflow its Session is in, here and in Fabric."""

from __future__ import annotations

from support.weaver_test import weaver_test

from weaver.run.record import open_run_record
from weaver.sessions.testing import TestSession
from weaver.workspaces import Workspace

WORKSPACE = Workspace(workspace="Sales Analytics", catalogue="Warehouse/Catalogue")


@weaver_test()
def test_a_run_outside_a_workflow_records_under_its_own_id():
    session = TestSession(workspace=WORKSPACE)

    first = open_run_record(None, task_type="Load", session=session)
    second = open_run_record(None, task_type="Load", session=session)

    assert session.workflow_id is None
    assert first.workflow_id != second.workflow_id


@weaver_test()
def test_runs_inside_a_workflow_record_under_its_id():
    session = TestSession(workspace=WORKSPACE)

    with session.workflow("outer"):
        first = open_run_record(None, task_type="Load", session=session)
        second = open_run_record(None, task_type="Test", session=session)

    assert (first.workflow_id, second.workflow_id) == ("outer", "outer")
    assert session.workflow_id is None


@weaver_test()
def test_a_nested_workflow_restores_the_outer_one_even_after_an_error():
    session = TestSession(workspace=WORKSPACE)

    with session.workflow("outer"):
        try:
            with session.workflow("inner"):
                assert session.workflow_id == "inner"
                raise RuntimeError("inside")
        except RuntimeError:
            pass
        assert session.workflow_id == "outer"


@weaver_test()
def test_a_run_sent_to_fabric_carries_the_workflow_it_was_sent_from():
    from weaver.sessions.program import FabricRun
    from weaver.sessions.run_in_fabric import _program

    def entry(**_):  # pragma: no cover - only its name is used
        return {}

    run = FabricRun(
        name="load",
        needs_spark=True,
        call=lambda session: None,
        entry=entry,
        arguments=dict,
        decode=dict,
    )

    program = _program(run, WORKSPACE, "abfss://stage", workflow_id="w-1")

    assert "workflow_id='w-1'" in program.source


@weaver_test()
def test_fabric_records_a_staged_run_under_the_clients_workflow(monkeypatch):
    import json

    import weaver.lakehouse
    from weaver.run import entry as entry_module

    written = {}

    class Store:
        def read(self, location):
            return json.dumps({}).encode()

        def write(self, location, data):
            written["result"] = data

    monkeypatch.setattr("weaver.fabric.store.FabricStore", lambda: Store())
    monkeypatch.setattr(weaver.lakehouse, "release_mounts", lambda: None)
    monkeypatch.setattr(
        "weaver.sessions.run_in_fabric.progress_written",
        lambda session, store, location: _nothing(),
    )
    session = TestSession(workspace=WORKSPACE)
    seen = []

    def run(*, session, workspace):
        seen.append(session.workflow_id)
        return {}

    entry_module.run_staged(
        run, session=session, workspace=WORKSPACE, stage="stage", workflow_id="w-1"
    )

    assert seen == ["w-1"]
    assert session.workflow_id is None


def _nothing():
    from contextlib import nullcontext

    return nullcontext()
