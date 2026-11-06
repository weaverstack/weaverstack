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

    # Central's table is waited on, as published, but nothing of Central's runs.
    assert [node.node_id for node in graph.nodes if node.logical_id] == [
        "Sales::load:Warehouse/Mart_WH/MART.Summary"
    ]
    assert {node.owner for node in graph.nodes if node.owner == "Central"} <= {
        "Central"
    }
    assert {node.primitive_kind for node in graph.nodes if node.owner == "Central"} <= {
        "onelake_publication"
    }


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
    assert Lanes().of(finance, "Finance") != Lanes().of(sales, "Sales")
    # Two catalogues in one workspace share its Warehouse's lane.
    assert Lanes().of(finance, "Shared") == Lanes().of(sales, "shared")
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
    # The Mart reads the Bridge through its endpoint, which is synced first even
    # though Central's load does not run.
    assert [node_id for node_id, _ in dispatched] == [
        GOLD_PUBLISH,
        "Sales::refresh:Lakehouse/Bridge_LH",
        "Sales::load:Warehouse/Mart_WH/MART.Summary",
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

    loads = {workspace for node_id, workspace in dispatched if ":load:" in node_id}
    assert loads == {"Sales"}


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

    assert [node_id for node_id, _ in dispatched if ":load:" in node_id] == [
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


# --- paths the planner must keep --------------------------------------------------


def _gamma() -> Catalogue:
    """Gamma shortcuts Alpha's Summary, which sits in a cycle with Beta."""

    lake = WeaverItemId.parse("Lakehouse/Gamma")
    source = "Lakehouse/Gamma/Tables/A.Summary"
    total = "Lakehouse/Gamma/Tables/G.Total"
    physical = shortcut_row(
        source, "Lakehouse/Alpha_LH/Tables/A.Summary", target_type="physical"
    )
    physical["target_workspace_name"] = "Alpha"
    loadable = document_id(total)
    return Catalogue(
        rows={
            lake: {
                "Installation": (installation_row(lake, "Gamma_LH"),),
                "Registry": (
                    registry_row(source, object_role="shortcut"),
                    registry_row(loadable),
                    registry_row(
                        "Lakehouse/Gamma/file:_/Load/Tables/G__Total.py",
                        object_type="file",
                        object_role="load",
                    ),
                ),
                "Shortcut": (physical,),
                "Dependency": (dependency_row(total, "A.Summary"),),
            }
        }
    )


@weaver_test()
def test_a_reader_downstream_of_a_cycle_plans_without_circling_it():
    cycle = _cycle_members(summary=None, live=None)
    held = RunState.joined(
        [
            *(place(member.label, member.catalogue) for member in cycle),
            place("Gamma", _gamma()),
        ]
    )

    graph = plan(held, items(("Gamma", ("Lakehouse/Gamma",))), dry_run=True)

    assert [node.node_id for node in graph.nodes if node.logical_id] == [
        "Gamma::load:Lakehouse/Gamma_LH/Tables/G.Total"
    ]


def _two_bridges() -> Catalogue:
    """The Mart reads Central's Gold through two Bridge Lakehouses."""

    found = team()
    rows = {item: dict(tables) for item, tables in found.rows.items()}
    other = WeaverItemId.parse("Lakehouse/Other")
    other_bridge = "Lakehouse/Other/Tables/GOLD.CustomerSales"
    physical = shortcut_row(
        other_bridge, "Warehouse/Gold_WH/GOLD.CustomerSales", target_type="physical"
    )
    physical["target_workspace_name"] = "Central"
    rows[other] = {
        "Installation": (installation_row(other, "Other_LH"),),
        "Registry": (registry_row(other_bridge, object_role="shortcut"),),
        "Shortcut": (physical,),
    }
    mart = WeaverItemId.parse("Warehouse/Mart")
    copy = "Warehouse/Mart/COPY.CustomerSales"
    rows[mart] = {
        **rows[mart],
        "Registry": (
            *rows[mart]["Registry"],
            registry_row(copy, object_type="view", object_role="shortcut"),
        ),
        "Shortcut": (*rows[mart]["Shortcut"], shortcut_row(copy, other_bridge)),
        "Dependency": (
            *rows[mart]["Dependency"],
            dependency_row(SUMMARY, "COPY.CustomerSales"),
        ),
    }
    return Catalogue(rows=rows)


@weaver_test()
def test_a_table_read_through_two_bridges_waits_for_both():
    graph = plan(
        state(("Central", central()), ("Sales", _two_bridges())),
        items(
            ("Central", ("Warehouse/Gold",)),
            ("Sales", ("Lakehouse/Bridge", "Lakehouse/Other", "Warehouse/Mart")),
        ),
    )

    summary = "Sales::load:Warehouse/Mart_WH/MART.Summary"
    upstream = graph.topology.upstream_of(summary)
    assert set(upstream) == {
        "Sales::refresh:Lakehouse/Bridge_LH",
        "Sales::refresh:Lakehouse/Other_LH",
    }
    (publication,) = [
        node for node in graph.nodes if node.primitive_kind == "onelake_publication"
    ]
    assert sorted(str(each.target) for each in publication.publication_targets) == [
        "Lakehouse/Bridge_LH",
        "Lakehouse/Other_LH",
    ]


# --- review fixes: identity, selection, mirrors, build freshness -------------------


@weaver_test()
def test_a_joined_run_checks_installations_without_a_working_catalogue(monkeypatch):
    import weaver.run.identity as identity

    asked = []

    def check(catalogue, nodes, *, session, workspace):
        asked.append(workspace.workspace)
        from weaver.run.result import CATALOGUE_BINDING_INVALID, error

        return {
            node.node_id: (error(CATALOGUE_BINDING_INVALID, "replaced", source="test"),)
            for node in nodes
            if node.owner == "Sales"
        }

    monkeypatch.setattr(identity, "identity_messages", check)
    held = state(("Central", central()), ("Sales", team()))
    calls = []
    result = Runner(
        held,
        RunRequest.load(items(*EVERYTHING), fault_tolerant=True),
        workspace=Workspace(workspace="Sales"),
    ).run(
        session=object(),
        dispatch=lambda node, **asked: (
            calls.append(node.node_id) or LoadResult(succeeded=True)
        ),
    )

    assert sorted(asked) == ["Central", "Sales"]
    assert not [each for each in calls if each.startswith("Sales::")]
    assert {node.status for node in result.nodes if node.catalogue == "Sales"} <= {
        "invalid",
        "blocked",
    }


def _places(*named):
    from weaver.operations.joined import Place

    return tuple(
        Place(
            label, Workspace(workspace=workspace, catalogue=f"Warehouse/{name}"), name
        )
        for label, workspace, name in named
    )


@weaver_test()
@pytest.mark.parametrize("reverse", [False, True])
def test_two_catalogues_in_the_working_workspace_are_ambiguous(reverse):
    from weaver.operations.joined import default_request, requested_by_label

    places = _places(
        ("Finance/Weaver", "Finance", "Weaver"),
        ("Finance/Archive", "Finance", "Archive"),
    )
    if reverse:
        places = places[::-1]
    home = Workspace(workspace="Finance")

    with pytest.raises(CommandError, match="several catalogues in Finance"):
        default_request("load", places, home)
    with pytest.raises(CommandError, match="several catalogues in Finance"):
        requested_by_label("load", ["Finance/Warehouse/Mart"], places, home)
    assert requested_by_label(
        "load", ["Finance/Warehouse/Archive/Warehouse/Mart"], places, home
    ) == {"Finance/Archive": (WeaverItemId.parse("Warehouse/Mart"),)}
    configured = Workspace(workspace="Finance", catalogue="Warehouse/Archive")
    assert default_request("load", places, configured) == {"Finance/Archive": ()}


@weaver_test()
def test_power_bi_selectors_are_the_working_workspaces_beside_context(monkeypatch):
    import weaver.operations.items as module
    from weaver.operations.joined import requested_by_label

    model = WeaverItemId.parse("SemanticModel/Sales")
    monkeypatch.setattr(
        module, "_powerbi_models", lambda value, *, project, what: (model,)
    )
    places = _places(("Central", "Central", "Weaver"), ("Sales", "Sales", "Weaver"))

    assert requested_by_label(
        "load", ["PowerBI"], places, Workspace(workspace="Sales"), project=object()
    ) == {"Sales": (model,)}


@weaver_test()
def test_an_unrelated_mirrored_catalogue_does_not_refuse_stale_selection(monkeypatch):
    from test_health_representation import REPORTING, YESTERDAY, _Estate, at

    import weaver.operations.mirror as mirror
    from weaver.operations.load import _stale_across

    mirrored = (
        _Estate()
        .table(f"{REPORTING}/Sales.Customer", loaded=at(10))
        .mirrors(f"{REPORTING}/Sales.Customer")
        .catalogue()
    )

    def refuse(catalogue, **asked):
        if catalogue is mirrored:
            raise CommandError("needs the source catalogue for mirrored objects")
        return None

    monkeypatch.setattr(mirror, "mirrored_source", refuse)

    selected, _left = _stale_across(
        None,
        state(("Central", central()), ("Sales", team()), ("Archive", mirrored)),
        items(("Sales", ("Warehouse/Mart",))),
        as_of=YESTERDAY,
    )

    assert selected


@weaver_test()
def test_a_producer_rebuilt_in_another_catalogue_makes_a_passed_test_stale():
    from datetime import datetime, timezone

    from factories import validation_row, validation_status_row

    from weaver.catalogues import Member, join
    from weaver.etl import validation_artefact_id
    from weaver.health import assess_validations, joined_statuses

    passed = datetime(2026, 11, 5, 9, tzinfo=timezone.utc)
    rebuilt = datetime(2026, 11, 5, 10, tzinfo=timezone.utc)
    gold = WeaverItemId.parse("Warehouse/Gold")
    producer = Catalogue(
        rows={
            gold: {
                "Installation": (installation_row(gold, "Gold_WH"),),
                "Registry": (
                    registry_row(GOLD, build_datetime=rebuilt),
                    *_loadable_warehouse(GOLD)[1:],
                ),
                "LoadStatus": (
                    load_status_row(GOLD, started_at=passed, completed_at=passed),
                ),
            }
        }
    )
    consumer_rows = {item: dict(tables) for item, tables in team().rows.items()}
    mart = WeaverItemId.parse("Warehouse/Mart")
    check = document_id("Warehouse/Mart/MART.CustomersArrive")
    consumer_rows[mart]["TestDictionary"] = (validation_row(check),)
    consumer_rows[mart]["Registry"] = (
        *consumer_rows[mart]["Registry"],
        registry_row(
            validation_artefact_id(mart, "Test", check.object_id),
            object_type="stored_procedure",
            object_role="test",
        ),
    )
    consumer_rows[mart]["Dependency"] = (
        *consumer_rows[mart]["Dependency"],
        dependency_row(check, "GOLD.CustomerSales"),
    )
    consumer_rows[mart]["TestStatus"] = (
        validation_status_row(check, started_at=passed, completed_at=passed),
    )
    consumer = Catalogue(rows=consumer_rows)
    members = [
        Member("Central", "Central", "Weaver", producer, producer.dag()),
        Member("Sales", "Sales", "Weaver", consumer, consumer.dag()),
    ]
    statuses, _unknown = joined_statuses(members)

    stale = assess_validations(
        consumer,
        items=(mart,),
        across=join(members).across(members[1], statuses),
    ).unsettled_identities()

    assert check in stale


# --- a producer this run does not load ----------------------------------------------


@weaver_test()
def test_a_reader_waits_for_publication_of_a_table_this_run_does_not_load():
    graph = plan(
        state(("Central", central()), ("Sales", team())),
        items(("Sales", ("Lakehouse/Bridge", "Warehouse/Mart"))),
    )

    by_id = graph.by_id
    assert GOLD_LOAD not in by_id
    publication = by_id[GOLD_PUBLISH]
    assert publication.produced_by is None
    assert set(graph.edges) == {
        (GOLD_PUBLISH, "Sales::refresh:Lakehouse/Bridge_LH"),
        (
            "Sales::refresh:Lakehouse/Bridge_LH",
            "Sales::load:Warehouse/Mart_WH/MART.Summary",
        ),
    }


@weaver_test()
@pytest.mark.parametrize("started", [None, "2026-11-06T01:00:00+00:00"])
def test_that_wait_needs_a_last_load_that_wrote_rows(monkeypatch, started):
    from datetime import datetime

    import weaver.run.publication as publication
    from weaver.run.dispatch import dispatch_primitive

    waited = []
    monkeypatch.setattr(
        publication,
        "last_load",
        lambda node, session, workspace: (
            None if started is None else datetime.fromisoformat(started)
        ),
    )
    monkeypatch.setattr(
        publication,
        "commits_before",
        lambda node, session, workspace, at: frozenset({"00000.json"}),
    )
    monkeypatch.setattr(
        publication,
        "await_publication",
        lambda node, session, workspace, **asked: waited.append(asked["before"]),
    )
    held = state(("Central", central()), ("Sales", team()))
    graph = plan(held, items(("Sales", ("Lakehouse/Bridge", "Warehouse/Mart"))))

    result = dispatch_primitive(
        graph.by_id[GOLD_PUBLISH],
        session=object(),
        state=held,
        workspace=held.by_label["Central"].workspace,
    )

    assert result.succeeded
    assert waited == ([] if started is None else [frozenset({"00000.json"})])


@weaver_test()
def test_commits_before_a_load_are_told_apart_by_their_own_instants():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from weaver.locations import Location
    from weaver.run.publication import commits_before
    from weaver.store import Entry

    started = datetime(2026, 11, 6, 1, tzinfo=timezone.utc)
    stamp = started.timestamp() * 1000
    files = {
        # A table's first commit holds its metadata and no files.
        "0000a.json": json.dumps({"metaData": {}}) + "\n" + json.dumps({"txn": {}}),
        "00000.json": json.dumps({"commitInfo": {"timestamp": stamp - 60_000}}),
        "00001.json": json.dumps({"commitInfo": {"timestamp": stamp + 2_000}}),
        # A Fabric Warehouse commit carries no commitInfo, only its files'.
        "00002.json": json.dumps(
            {"add": {"path": "a", "modificationTime": stamp - 90_000}}
        ),
        "00003.json": json.dumps(
            {"add": {"path": "b", "modificationTime": stamp + 1_000}}
        ),
    }

    class Store:
        def exists(self, location):
            return True

        def list(self, location):
            return [
                Entry(location=Location(f"abfss://w@x/log/{name}"), is_directory=False)
                for name in files
            ]

        def read(self, location):
            return files[str(location).rsplit("/", 1)[-1]].encode()

    session = SimpleNamespace(transport_store=lambda workspace: Store())
    node = SimpleNamespace(
        physical_target=SimpleNamespace(name="Gold_WH"),
        publication_of=document_id(GOLD),
    )
    import weaver.run.publication as publication

    original = publication._commit_log
    publication._commit_log = lambda *a: Location(
        "abfss://w@x/Tables/GOLD/x/_delta_log"
    )
    try:
        assert commits_before(node, session, None, started) == {
            "0000a.json",
            "00000.json",
            "00002.json",
        }
    finally:
        publication._commit_log = original
