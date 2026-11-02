"""What ``weaver test --stale`` runs.

``weaver health`` and a stale test both read
:func:`weaver.health.assess_validations`, so these tests compare what the
report calls not Green with what the run selects. The freshness rules
themselves belong to ``test_health_representation``.
"""

from __future__ import annotations

import pytest
from support.weaver_test import weaver_test
from support.workspaces import given_workspace
from test_health_representation import CURATED, RAW, _Estate, at

import weaver
from weaver.catalogue.tables import LOAD_STATUS, TEST_STATUS
from weaver.declaration.model import WeaverItemId
from weaver.errors import CommandError, ValidationError
from weaver.health import GREEN, assess_validations
from weaver.operations.test import run_test
from weaver.run import RunRequest, RunState

RAW_ITEM = WeaverItemId.parse(RAW)
CURATED_ITEM = WeaverItemId.parse(CURATED)


def mixed_estate() -> _Estate:
    """One validation in each state the policy distinguishes."""

    return (
        _Estate()
        .table(f"{RAW}/Tables/Sales.Order", loaded=at(1), moved=at(1))
        .table(f"{RAW}/Tables/Sales.Archive", loaded=at(10), moved=at(10))
        # Passed after what it reads last loaded.
        .validation(f"{RAW}/Sales.Current", result="succeeded", ran=at(5))
        .reads(f"{RAW}/Sales.Current", "Sales.Archive")
        # Passed, then Sales.Order loaded again.
        .validation(f"{RAW}/Sales.Behind", result="succeeded", ran=at(3))
        .reads(f"{RAW}/Sales.Behind", "Sales.Order")
        # Failed, and nothing it reads has moved since.
        .validation(
            f"{RAW}/Sales.FailedUnchanged", result="failed", ran=at(5), failure_count=2
        )
        .reads(f"{RAW}/Sales.FailedUnchanged", "Sales.Archive")
        # Failed, and what it reads has moved since.
        .validation(
            f"{RAW}/Sales.FailedMoved", result="failed", ran=at(3), failure_count=1
        )
        .reads(f"{RAW}/Sales.FailedMoved", "Sales.Order")
        .validation(f"{RAW}/Sales.Errored", result="error", ran=at(5))
        .validation(f"{RAW}/Sales.Rebuilt", result="pending")
        .validation(f"{RAW}/Sales.NeverRun")
        .validation(f"{CURATED}/Sales.Elsewhere")
    )


STALE = {
    f"{RAW}/Sales.Behind",
    f"{RAW}/Sales.FailedUnchanged",
    f"{RAW}/Sales.FailedMoved",
    f"{RAW}/Sales.Errored",
    f"{RAW}/Sales.Rebuilt",
    f"{RAW}/Sales.NeverRun",
}


def not_green(report_section) -> set[str]:
    return {finding.object_id for finding in report_section.findings}


@pytest.fixture
def prepared():
    from support.sessions import given_session

    workspace = given_workspace(catalogue="Warehouse/Weaver")
    return workspace, given_session(workspace=workspace)


def dry_run(prepared, catalogue, **policy):
    workspace, session = prepared
    return run_test(
        session,
        workspace=workspace,
        state=RunState(catalogue=catalogue),
        dry_run=True,
        **policy,
    )


def ran(report) -> set[str]:
    return {node.logical_id for node in report.nodes}


# --- the equivalence invariant ------------------------------------------------


@weaver_test()
def test_stale_selection_is_what_health_does_not_call_green():
    catalogue = mixed_estate().catalogue()
    assessment = assess_validations(catalogue, items=(RAW_ITEM,))
    report = mixed_estate().report(targets=None)

    selected = {str(each) for each in assessment.unsettled_identities()}
    reported = {
        str(subject.identity)
        for subject in assessment.subjects
        if subject.severity != GREEN
    }
    assert selected == reported == STALE
    assert not_green(assessment.to_health_section()) <= not_green(report.tests)


@weaver_test()
def test_health_renders_the_same_assessment():
    catalogue = mixed_estate().catalogue()

    assert assess_validations(catalogue).to_health_section() == (
        mixed_estate().report().tests
    )


# --- the policy ---------------------------------------------------------------


@weaver_test()
def test_a_stale_run_selects_never_run_failed_and_behind_validations(prepared):
    report = dry_run(
        prepared, mixed_estate().catalogue(), items=(RAW_ITEM,), stale=True
    )

    assert ran(report) == STALE


@weaver_test()
def test_a_failure_is_selected_whether_or_not_its_inputs_moved(prepared):
    """Failure and staleness are separate questions; either selects."""

    report = dry_run(
        prepared, mixed_estate().catalogue(), items=(RAW_ITEM,), stale=True
    )

    assert {f"{RAW}/Sales.FailedUnchanged", f"{RAW}/Sales.FailedMoved"} <= ran(report)


@weaver_test()
def test_a_current_pass_is_not_selected(prepared):
    report = dry_run(
        prepared, mixed_estate().catalogue(), items=(RAW_ITEM,), stale=True
    )

    assert f"{RAW}/Sales.Current" not in ran(report)


@weaver_test()
def test_without_stale_every_validation_runs(prepared):
    report = dry_run(prepared, mixed_estate().catalogue(), items=(RAW_ITEM,))

    assert ran(report) == STALE | {f"{RAW}/Sales.Current"}


@weaver_test()
def test_the_item_scope_still_bounds_a_stale_run(prepared):
    report = dry_run(
        prepared, mixed_estate().catalogue(), items=(RAW_ITEM,), stale=True
    )

    assert f"{CURATED}/Sales.Elsewhere" not in ran(report)


@weaver_test()
def test_names_narrow_a_stale_run(prepared):
    report = dry_run(
        prepared,
        mixed_estate().catalogue(),
        items=(RAW_ITEM,),
        names=("Sales.Failed.*",),
        stale=True,
    )

    assert ran(report) == {f"{RAW}/Sales.FailedUnchanged", f"{RAW}/Sales.FailedMoved"}


@weaver_test()
def test_a_name_matching_only_current_validations_selects_nothing(prepared):
    report = dry_run(
        prepared,
        mixed_estate().catalogue(),
        items=(RAW_ITEM,),
        names=("Sales.Current",),
        stale=True,
    )

    assert report.nodes == ()
    assert report.succeeded


@weaver_test()
def test_a_name_matching_nothing_is_still_refused(prepared):
    with pytest.raises(ValidationError, match="no installed validation"):
        dry_run(
            prepared,
            mixed_estate().catalogue(),
            items=(RAW_ITEM,),
            names=("Sales.Missing",),
            stale=True,
        )


@weaver_test()
def test_a_current_estate_selects_nothing_and_succeeds(prepared):
    catalogue = (
        _Estate()
        .table(f"{RAW}/Tables/Sales.Order", loaded=at(5), moved=at(5))
        .validation(f"{RAW}/Sales.Current", result="succeeded", ran=at(1))
        .reads(f"{RAW}/Sales.Current", "Sales.Order")
        .catalogue()
    )

    report = dry_run(prepared, catalogue, items=(RAW_ITEM,), stale=True)

    assert report.nodes == ()
    assert report.succeeded
    assert report.succeeded


# --- what the run reads and sends ---------------------------------------------


def _reading(monkeypatch, catalogue):
    seen = {}

    def recorder(*, session, workspace, tables=None):
        seen["tables"] = tables
        return catalogue

    monkeypatch.setattr("weaver.run.state.read_installed_catalogue", recorder)
    return seen


@weaver_test()
def test_a_stale_run_reads_test_and_load_status_with_the_catalogue(
    prepared, monkeypatch
):
    seen = _reading(monkeypatch, mixed_estate().catalogue())
    workspace, session = prepared

    run_test(session, workspace=workspace, items=(RAW_ITEM,), dry_run=True, stale=True)

    assert {TEST_STATUS, LOAD_STATUS} <= set(seen["tables"])


@weaver_test()
def test_an_ordinary_run_reads_no_status(prepared, monkeypatch):
    seen = _reading(monkeypatch, mixed_estate().catalogue())
    workspace, session = prepared

    run_test(session, workspace=workspace, items=(RAW_ITEM,), dry_run=True)

    assert seen["tables"] is None


@weaver_test()
def test_the_selection_crosses_to_fabric_with_the_request():
    selected = tuple(
        sorted(
            assess_validations(mixed_estate().catalogue()).unsettled_identities(),
            key=str,
        )
    )
    request = RunRequest.test((RAW_ITEM,), selected=selected, fault_tolerant=True)

    carried = RunRequest.from_mapping(request.to_mapping())

    assert carried.selected == selected
    assert carried.kind == request.kind


# --- where stale has nothing to read ------------------------------------------


@weaver_test()
def test_stale_with_files_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(CommandError, match="files record none"):
        weaver.test(
            workspace="Sales Analytics",
            catalogue="Warehouse/Weaver",
            files=str(tmp_path / "Sales.Check.sql"),
            stale=True,
        )


@weaver_test()
def test_stale_without_a_catalogue_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(CommandError, match="test --stale needs a Weaver catalogue"):
        weaver.test(workspace="Sales Analytics", stale=True)
