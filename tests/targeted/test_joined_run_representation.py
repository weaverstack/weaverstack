"""One load or test across catalogues: one composed graph, one Runner.

Central loads ``GOLD.CustomerSales`` into its Warehouse. Sales and Finance each
shortcut it into a Bridge Lakehouse and read it into a Mart Warehouse through
the Bridge's SQL endpoint, with the same item and object names. Every node is
qualified by the catalogue that owns it, runs in that catalogue's workspace and
is recorded there.
"""

from __future__ import annotations

import json

import pytest
from factories import (
    dependency_row,
    document_id,
    installation_row,
    load_status_row,
    registry_row,
    shortcut_row,
)
from support.catalogues import Recording
from support.weaver_test import weaver_test
from test_joined_health_representation import (
    _cycle_members,
    _loadable_warehouse,
    alpha_and_beta,
)

from weaver.catalogue.state import Catalogue
from weaver.catalogue.tables import LOAD_STATUS, TEST_STATUS
from weaver.declaration.model import WeaverItemId
from weaver.errors import CommandError
from weaver.joined_dag import Owned
from weaver.load_report import LoadRunReport
from weaver.run import Runner, RunRequest, RunState
from weaver.run.runner import Lanes
from weaver.run.state import RunPlace
from weaver.runtime.load_result import LoadResult
from weaver.workspaces import Workspace

GOLD = "Warehouse/Gold/GOLD.CustomerSales"
BRIDGE = "Lakehouse/Bridge/Tables/GOLD.CustomerSales"
MART_SHORTCUT = "Warehouse/Mart/GOLD.CustomerSales"
SUMMARY = "Warehouse/Mart/MART.Summary"

GOLD_LOAD = "Central::load:Warehouse/Gold_WH/GOLD.CustomerSales"
GOLD_PUBLISH = "Central::publish:Warehouse/Gold_WH/GOLD.CustomerSales"


def central(writer=None) -> Catalogue:
    gold = WeaverItemId.parse("Warehouse/Gold")
    return Catalogue(
        rows={
            gold: {
                "Installation": (installation_row(gold, "Gold_WH"),),
                "Registry": tuple(_loadable_warehouse(GOLD)),
                "LoadStatus": (load_status_row(GOLD),),
            }
        },
        writer=writer,
    )


def team(writer=None, *, validation=False) -> Catalogue:
    """A team that reads Central's Gold through its Bridge into its Mart."""

    bridge = WeaverItemId.parse("Lakehouse/Bridge")
    mart = WeaverItemId.parse("Warehouse/Mart")
    physical = shortcut_row(
        BRIDGE, "Warehouse/Gold_WH/GOLD.CustomerSales", target_type="physical"
    )
    physical["target_workspace_name"] = "Central"
    mart_rows = {
        "Installation": (installation_row(mart, "Mart_WH"),),
        "Registry": (
            *_loadable_warehouse(SUMMARY),
            registry_row(MART_SHORTCUT, object_type="view", object_role="shortcut"),
        ),
        "Shortcut": (shortcut_row(MART_SHORTCUT, BRIDGE),),
        "Dependency": (dependency_row(SUMMARY, "GOLD.CustomerSales"),),
        "LoadStatus": (load_status_row(SUMMARY),),
    }
    if validation:
        from factories import validation_row

        from weaver.etl import validation_artefact_id

        check = document_id("Warehouse/Mart/MART.SummaryHasRows")
        artefact = validation_artefact_id(mart, "Test", check.object_id)
        mart_rows["TestDictionary"] = (validation_row(check, test_type="test"),)
        mart_rows["Registry"] = (
            *mart_rows["Registry"],
            registry_row(artefact, object_type="stored_procedure", object_role="test"),
        )
    return Catalogue(
        rows={
            bridge: {
                "Installation": (installation_row(bridge, "Bridge_LH"),),
                "Registry": (registry_row(BRIDGE, object_role="shortcut"),),
                "Shortcut": (physical,),
            },
            mart: mart_rows,
        },
        writer=writer,
    )


def place(label: str, catalogue: Catalogue) -> RunPlace:
    return RunPlace(
        label, Workspace(workspace=label, catalogue="Warehouse/Weaver"), catalogue
    )


def state(*catalogues) -> RunState:
    return RunState.joined(place(label, held) for label, held in catalogues)


def items(*named) -> tuple[Owned, ...]:
    return tuple(
        Owned(label, WeaverItemId.parse(item))
        for label, chosen in named
        for item in chosen
    )


EVERYTHING = (
    ("Central", ("Warehouse/Gold",)),
    ("Sales", ("Lakehouse/Bridge", "Warehouse/Mart")),
)


def plan(held: RunState, chosen, **policy):
    return Runner(held, RunRequest.load(chosen, **policy)).plan()


def reaches(graph, upstream: str, downstream: str) -> bool:
    return downstream in graph.topology.descendants(upstream)


# --- one composed graph -------------------------------------------------------


@weaver_test()
def test_a_reader_in_another_catalogue_waits_for_publication_then_its_endpoint():
    graph = plan(state(("Central", central()), ("Sales", team())), items(*EVERYTHING))

    by_id = graph.by_id
    assert set(by_id) == {
        GOLD_LOAD,
        GOLD_PUBLISH,
        "Sales::refresh:Lakehouse/Bridge_LH",
        "Sales::load:Warehouse/Mart_WH/MART.Summary",
    }
    assert set(graph.edges) == {
        (GOLD_LOAD, GOLD_PUBLISH),
        (GOLD_PUBLISH, "Sales::refresh:Lakehouse/Bridge_LH"),
        (
            "Sales::refresh:Lakehouse/Bridge_LH",
            "Sales::load:Warehouse/Mart_WH/MART.Summary",
        ),
    }
    (readiness,) = by_id[GOLD_PUBLISH].publication_targets
    assert (readiness.owner, str(readiness.target)) == ("Sales", "Lakehouse/Bridge_LH")
    assert by_id["Sales::refresh:Lakehouse/Bridge_LH"].refresh_tables == (
        ("GOLD", "CustomerSales"),
    )
    summary = by_id["Sales::load:Warehouse/Mart_WH/MART.Summary"]
    assert (summary.owner, str(summary.logical_id), str(summary.physical_target)) == (
        "Sales",
        SUMMARY,
        "Warehouse/Mart_WH",
    )


@weaver_test()
def test_a_catalogue_given_for_context_runs_nothing():
    graph = plan(
        state(("Central", central()), ("Sales", team())),
        items(("Sales", ("Warehouse/Mart",))),
    )

    assert [node.node_id for node in graph.nodes] == [
        "Sales::load:Warehouse/Mart_WH/MART.Summary"
    ]


@weaver_test()
def test_identical_names_in_two_catalogues_stay_distinct():
    graph = plan(
        state(("Central", central()), ("Sales", team()), ("Finance", team())),
        items(
            *EVERYTHING,
            ("Finance", ("Lakehouse/Bridge", "Warehouse/Mart")),
        ),
    )

    marts = [node for node in graph.nodes if node.logical_id is not None]
    assert sorted((node.owner, str(node.logical_id)) for node in marts) == [
        ("Central", GOLD),
        ("Finance", SUMMARY),
        ("Sales", SUMMARY),
    ]
    finance, sales = sorted(
        (node for node in marts if str(node.logical_id) == SUMMARY),
        key=lambda node: node.owner,
    )
    assert Lanes().of(finance) != Lanes().of(sales)
    assert reaches(graph, GOLD_LOAD, finance.node_id)
    assert reaches(graph, GOLD_LOAD, sales.node_id)


@weaver_test()
def test_reading_back_through_another_catalogue_keeps_the_order_and_is_no_cycle():
    """Alpha's Raw feeds Beta's live View, which Alpha's Summary reads."""

    held = RunState.joined(
        place(member.label, member.catalogue) for member in alpha_and_beta()
    )
    graph = plan(held, items(("Alpha", ("Lakehouse/Alpha",))))

    loads = [node.node_id for node in graph.nodes if node.logical_id is not None]
    assert sorted(loads) == [
        "Alpha::load:Lakehouse/Alpha_LH/Tables/A.Raw",
        "Alpha::load:Lakehouse/Alpha_LH/Tables/A.Summary",
    ]
    assert reaches(
        graph,
        "Alpha::load:Lakehouse/Alpha_LH/Tables/A.Raw",
        "Alpha::load:Lakehouse/Alpha_LH/Tables/A.Summary",
    )
    assert not [each for each in graph.messages if each.code == "dag_cycle"]


@weaver_test()
def test_a_cycle_across_catalogues_runs_each_node_once_and_is_reported():
    held = RunState.joined(
        place(member.label, member.catalogue)
        for member in _cycle_members(summary=None, live=None)
    )
    request = RunRequest.load(
        items(("Alpha", ("Lakehouse/Alpha",)), ("Beta", ("Warehouse/Serving",)))
    )
    calls = []

    def dispatch(node, **asked):
        calls.append(node.node_id)
        return LoadResult(succeeded=True)

    result = Runner(held, request).run(dispatch=dispatch)

    loads = [each for each in calls if ":load:" in each]
    assert len(loads) == len(set(loads)) == 3
    assert [each for each in result.messages if each.code == "dag_cycle"]


@weaver_test()
@pytest.mark.parametrize("fault_tolerant", [False, True])
def test_a_failed_publication_blocks_its_reader(fault_tolerant):
    held = state(("Central", central()), ("Sales", team()))
    request = RunRequest.load(items(*EVERYTHING), fault_tolerant=fault_tolerant)

    def dispatch(node, **asked):
        if node.node_id == GOLD_PUBLISH:
            raise RuntimeError("no new commit appeared")
        return LoadResult(succeeded=True, rows_inserted=1)

    result = Runner(held, request).run(dispatch=dispatch)

    statuses = {node.node_id: node.status for node in result.nodes}
    assert statuses[GOLD_PUBLISH] == "failed"
    assert statuses["Sales::load:Warehouse/Mart_WH/MART.Summary"] in (
        "blocked",
        "pending",
    )
    assert statuses["Sales::load:Warehouse/Mart_WH/MART.Summary"] != "succeeded"


# --- each node in its own workspace and catalogue -----------------------------


@weaver_test()
def test_each_node_runs_in_its_workspace_and_is_recorded_in_its_catalogue():
    from support.sessions import given_session

    from weaver.operations.load import execute_load
    from weaver.run.runner import Runner as Made

    writers = {"Central": Recording(), "Sales": Recording()}
    held = state(
        ("Central", central(writers["Central"])),
        ("Sales", team(writers["Sales"])),
    )
    home = held.by_label["Sales"].workspace
    runner = Made(held, RunRequest.load(items(*EVERYTHING)), workspace=home)
    seen = {}

    def dispatch(node, **asked):
        seen[node.node_id] = asked["workspace"].workspace
        return LoadResult(succeeded=True, rows_inserted=1)

    import weaver.run as run

    session = given_session(workspace=home)
    original = run.dispatch_primitive
    run.dispatch_primitive = dispatch
    try:
        with session.workflow("one-workflow"):
            from datetime import datetime, timezone

            report = execute_load(
                session,
                workspace=home,
                runner=runner,
                started=datetime.now(timezone.utc),
            )
    finally:
        run.dispatch_primitive = original

    assert seen[GOLD_LOAD] == "Central"
    assert seen["Sales::load:Warehouse/Mart_WH/MART.Summary"] == "Sales"
    assert seen["Sales::refresh:Lakehouse/Bridge_LH"] == "Sales"
    central_status = writers["Central"].rows(LOAD_STATUS.name)
    sales_status = writers["Sales"].rows(LOAD_STATUS.name)
    assert [row["object_name"] for row in central_status] == ["CustomerSales"]
    assert [row["object_name"] for row in sales_status] == ["Summary"]
    assert {row["workflow_id"] for row in central_status + sales_status} == {
        "one-workflow"
    }
    assert report.workflow_id == "one-workflow"
    assert report.catalogues == (
        "Central/Warehouse/Weaver",
        "Sales/Warehouse/Weaver",
    )
    assert {node.catalogue for node in report.nodes} == {"Central", "Sales"}

    carried = json.loads(json.dumps(report.to_mapping()))
    assert LoadRunReport.from_mapping(carried).to_mapping() == report.to_mapping()
    assert carried["catalogues"] == list(report.catalogues)


@weaver_test()
def test_a_dry_run_dispatches_and_records_nothing():
    writers = {"Central": Recording(), "Sales": Recording()}
    held = state(
        ("Central", central(writers["Central"])),
        ("Sales", team(writers["Sales"])),
    )
    calls = []
    result = Runner(held, RunRequest.load(items(*EVERYTHING), dry_run=True)).run(
        dispatch=lambda node, **asked: calls.append(node)
    )

    assert calls == []
    assert {node.status for node in result.nodes} == {"validated"}
    assert all(writer.flushes == 0 for writer in writers.values())


# --- the public operations ----------------------------------------------------


@pytest.fixture
def estate(monkeypatch):
    """Two catalogues read from rows, and what each was read and asked."""

    from support.sessions import given_session

    import weaver.run as run
    import weaver.run.state as run_state

    writers = {"Central": Recording(), "Sales": Recording()}
    reads = []

    def read(*, session, workspace, tables=None):
        reads.append(workspace.workspace)
        if workspace.workspace == "Archive":
            raise ConnectionError("refused")
        return {"Central": central, "Sales": team}[workspace.workspace](
            writers[workspace.workspace]
        )

    dispatched = []

    def dispatch(node, **asked):
        dispatched.append((node.node_id, asked["workspace"].workspace))
        return LoadResult(succeeded=True, rows_inserted=1)

    monkeypatch.setattr(run_state, "read_installed_catalogue", read)
    monkeypatch.setattr(run, "dispatch_primitive", dispatch)
    import weaver.operations.joined as joined

    monkeypatch.setattr(joined, "retried", lambda work, **asked: work())
    session = given_session(workspace=Workspace(workspace="Sales"))
    return session, reads, dispatched, writers


CATALOGUES = ["Central/Warehouse/Weaver", "Sales/Warehouse/Weaver"]


@weaver_test()
def test_a_load_reads_each_catalogue_once_and_runs_the_working_catalogue(estate):
    import weaver

    session, reads, dispatched, writers = estate

    report = weaver.load(catalogue=CATALOGUES, session=session)

    assert sorted(reads) == ["Central", "Sales"]
    assert [node_id for node_id, _ in dispatched] == [
        "Sales::load:Warehouse/Mart_WH/MART.Summary"
    ]
    assert report.succeeded
    assert writers["Central"].rows(LOAD_STATUS.name) == []
    assert [row["object_name"] for row in writers["Sales"].rows(LOAD_STATUS.name)] == [
        "Summary"
    ]


@weaver_test()
def test_the_working_workspace_holds_even_when_another_catalogue_is_first(estate):
    import weaver

    session, _reads, dispatched, _writers = estate

    weaver.load(catalogue=CATALOGUES, workspace="Sales", session=session)

    assert {workspace for _, workspace in dispatched} == {"Sales"}


@weaver_test()
def test_naming_both_workspaces_runs_both_in_one_graph(estate):
    import weaver

    session, _reads, dispatched, _writers = estate

    report = weaver.load(["Central", "Sales"], catalogue=CATALOGUES, session=session)

    order = [node_id for node_id, _ in dispatched]
    assert order.index(GOLD_LOAD) < order.index(
        "Sales::load:Warehouse/Mart_WH/MART.Summary"
    )
    assert report.workflow_id is not None


@weaver_test()
def test_selection_options_reach_the_composed_graph(estate):
    import weaver

    session, _reads, dispatched, _writers = estate

    weaver.load(
        ["Sales/Warehouse/Mart"],
        names="MART.Summary",
        ancestors=True,
        catalogue=CATALOGUES,
        session=session,
    )

    assert [node_id for node_id, _ in dispatched] == [
        "Sales::load:Warehouse/Mart_WH/MART.Summary"
    ]


@weaver_test()
def test_an_unreadable_catalogue_refuses_the_load_before_any_work(estate):
    import weaver

    session, _reads, dispatched, _writers = estate

    with pytest.raises(CommandError, match="Archive"):
        weaver.load(
            catalogue=[*CATALOGUES, "Archive/Warehouse/Weaver"], session=session
        )
    assert dispatched == []


@weaver_test()
def test_reload_and_stale_together_are_refused_before_reading(estate):
    import weaver

    session, reads, _dispatched, _writers = estate

    with pytest.raises(CommandError, match="--reload and --stale"):
        weaver.load(catalogue=CATALOGUES, stale=True, reload=True, session=session)
    assert reads == []


@weaver_test()
def test_a_test_run_across_catalogues_records_each_validation_where_it_lives(
    monkeypatch, estate
):
    import weaver
    import weaver.operations.test as operation
    from weaver.runtime.validation_result import TestResult

    session, _reads, _dispatched, writers = estate
    import weaver.run.state as run_state

    finance_writer = Recording()
    held = {
        "Sales": team(writers["Sales"], validation=True),
        "Finance": team(finance_writer, validation=True),
    }
    monkeypatch.setattr(
        run_state,
        "read_installed_catalogue",
        lambda *, session, workspace, tables=None: held[workspace.workspace],
    )
    asked = []

    def dispatch(node, **policy):
        asked.append((node.node_id, policy["workspace"].workspace))
        return TestResult(missing_count=0, unexpected_count=0)

    monkeypatch.setattr(operation, "_dispatch_collecting", lambda collect: dispatch)

    report = weaver.test(
        ["Sales", "Finance"],
        catalogue=["Sales/Warehouse/Weaver", "Finance/Warehouse/Weaver"],
        session=session,
    )

    assert sorted(asked) == [
        ("Finance::Warehouse/Mart/MART.SummaryHasRows", "Finance"),
        ("Sales::Warehouse/Mart/MART.SummaryHasRows", "Sales"),
    ]
    assert [node.key for node in report.nodes] == [
        "Sales::Warehouse/Mart/MART.SummaryHasRows",
        "Finance::Warehouse/Mart/MART.SummaryHasRows",
    ]
    assert len(writers["Sales"].rows(TEST_STATUS.name)) == 1
    assert len(finance_writer.rows(TEST_STATUS.name)) == 1
    assert report.to_mapping()["catalogues"] == [
        "Sales/Warehouse/Weaver",
        "Finance/Warehouse/Weaver",
    ]


@weaver_test()
def test_files_with_several_catalogues_are_refused_before_any_work(estate):
    import weaver

    session, reads, _dispatched, _writers = estate

    with pytest.raises(CommandError, match="one catalogue"):
        weaver.test(files="tests/x.sql", catalogue=CATALOGUES, session=session)
    assert reads == []


# --- mirrored state -----------------------------------------------------------


@weaver_test()
def test_stale_selection_reads_mirrored_state_as_one_catalogue_does(monkeypatch):
    """The same mirrored estate selects the same objects with a context
    catalogue beside it."""

    from test_health_representation import REPORTING, YESTERDAY, _Estate, _source, at

    import weaver.operations.mirror as mirror
    from weaver.health import assess_load
    from weaver.operations.load import _stale_across

    mirrored = (
        _Estate()
        .table(f"{REPORTING}/Sales.Customer", loaded=at(10))
        .mirrors(f"{REPORTING}/Sales.Customer")
        .table(f"{REPORTING}/Sales.Summary", loaded=at(5), moved=at(5))
        .reads(f"{REPORTING}/Sales.Summary", "Sales.Customer")
        .catalogue()
    )
    source = _source((f"{REPORTING}/Sales.Customer", "succeeded", at(1)))
    monkeypatch.setattr(
        mirror,
        "mirrored_source",
        lambda catalogue, **asked: source if catalogue is mirrored else None,
    )
    alone = assess_load(
        mirrored,
        as_of=YESTERDAY,
        items=(WeaverItemId.parse(REPORTING),),
        source=source,
    ).unsettled_identities()

    selected, left = _stale_across(
        None,
        state(("Central", central()), ("Reporting", mirrored)),
        items(("Reporting", (REPORTING,))),
        as_of=YESTERDAY,
    )

    assert alone
    assert selected == tuple(Owned("Reporting", each) for each in alone)
