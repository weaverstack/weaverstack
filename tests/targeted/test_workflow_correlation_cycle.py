"""A Load and a Test in one workflow report and record its one workflow ID.

``execute_load`` and ``execute_test`` are where both positions record: a
client calls them in-process for TDS-only work, and Fabric calls them for a run
a client sent. Dispatch is injected, so what is under test is the recording.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from factories import (
    LOAD_CONSUMER,
    installed_catalogue,
    lakehouse_test,
    load_estate,
    load_estate_bindings,
)
from support.catalogues import Recording
from support.weaver_test import weaver_test
from support.workspaces import given_workspace

import weaver
from weaver.catalogue.tables import LOAD_STATUS, LOG, TEST_STATUS
from weaver.declaration.model import WeaverItemId
from weaver.operations.load import execute_load
from weaver.operations.test import execute_test, validation_runner
from weaver.run import Runner, RunRequest, RunState
from weaver.runtime.load_result import LoadResult
from weaver.sessions.testing import TestSession

RAW = WeaverItemId.parse("Lakehouse/Raw")
REPORTING = WeaverItemId.parse(LOAD_CONSUMER)


@pytest.fixture
def estate(tmp_path):
    root = tmp_path / "repository"
    load_estate(root)
    (root / "Lakehouse/Raw/tests").mkdir(parents=True)
    (root / "Lakehouse/Raw/tests/Sales__OrderHasRows.py").write_text(
        lakehouse_test("Sales.OrderHasRows", primary_key="OrderId"), encoding="utf-8"
    )
    from weaver.declaration import parse_item_repository
    from weaver.locations import Location

    catalogue = installed_catalogue(
        parse_item_repository(Location(str(root))), load_estate_bindings()
    )
    writer = Recording()
    catalogue._writer = writer
    return catalogue, writer


@pytest.fixture
def succeeding(monkeypatch):
    from weaver.runtime.validation_result import TestResult

    def dispatch(node, **policy):
        if node.role in ("test", "assumption"):
            return TestResult()
        return LoadResult(succeeded=True)

    monkeypatch.setattr("weaver.run.dispatch_primitive", dispatch)


def _now():
    return datetime.now(timezone.utc)


@weaver_test()
def test_a_load_and_a_test_record_under_one_workflow(estate, succeeding):
    catalogue, writer = estate
    workspace = given_workspace(catalogue="Warehouse/Weaver_LH")
    session = TestSession(workspace=workspace, executes_here=True)

    with weaver.workflow(session=session) as entered:
        load = execute_load(
            session,
            workspace=workspace,
            runner=Runner(
                RunState(catalogue=catalogue),
                RunRequest.load((RAW, REPORTING)),
                workspace=workspace,
                can_refresh=True,
            ),
            started=_now(),
        )
        test = execute_test(
            session,
            workspace=workspace,
            runner=validation_runner(
                workspace,
                RunState(catalogue=catalogue),
                RunRequest.test((RAW,), fault_tolerant=True),
            ),
            started=_now(),
        )

    recorded = {
        row["workflow_id"]
        for table in (LOG.name, LOAD_STATUS.name, TEST_STATUS.name)
        for row in writer.rows(table)
    }
    assert writer.rows(LOAD_STATUS.name) and writer.rows(TEST_STATUS.name)
    assert load.workflow_id == test.workflow_id == entered.workflow_id
    assert recorded == {entered.workflow_id}


@weaver_test()
def test_a_second_workflow_on_the_same_session_records_its_own_id(estate, succeeding):
    catalogue, writer = estate
    workspace = given_workspace(catalogue="Warehouse/Weaver_LH")
    session = TestSession(workspace=workspace, executes_here=True)
    ids = []

    for _ in range(2):
        with weaver.workflow(session=session) as entered:
            report = execute_test(
                session,
                workspace=workspace,
                runner=validation_runner(
                    workspace,
                    RunState(catalogue=catalogue),
                    RunRequest.test((RAW,), fault_tolerant=True),
                ),
                started=_now(),
            )
            ids.append((entered.workflow_id, report.workflow_id))

    (first, first_report), (second, second_report) = ids
    assert first == first_report and second == second_report and first != second
    assert [row["workflow_id"] for row in writer.rows(TEST_STATUS.name)] == [
        first,
        second,
    ]
