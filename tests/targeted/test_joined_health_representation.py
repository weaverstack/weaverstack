"""Health across catalogues: joined where a physical shortcut crosses, and each
catalogue assessed with ancestry through the others.

Two teams, each with its own catalogue. Central loads ``CORE.Customer``. Sales
shortcuts it into its Bridge Lakehouse, materialises ``SALES.Revenue`` from it,
and serves both through a semantic model: ``Customer`` in Direct Lake and
``Revenue`` in Import.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from factories import (
    dependency_row,
    document_id,
    installation_row,
    load_status_row,
    registry_row,
    shortcut_row,
)
from support.weaver_test import weaver_test

from weaver.catalogue.state import Catalogue
from weaver.catalogues import Member, join
from weaver.declaration.model import WeaverDocumentId, WeaverItemId
from weaver.health import (
    AMBER,
    GREEN,
    LOAD_ANCESTOR_UNESTABLISHED,
    LOAD_ANCESTOR_UNOBSERVED,
    LOAD_STALE_ANCESTOR,
    Unread,
    assess_joined,
)

NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
EARLIER = NOW - timedelta(hours=2)
LATER = NOW - timedelta(minutes=5)

CORE = "Lakehouse/Core"
BRIDGE = "Lakehouse/Bridge"
MODEL = WeaverItemId.parse("SemanticModel/Sales")

PRODUCER = f"{CORE}/Tables/CORE.Customer"
DESTINATION = f"{BRIDGE}/Tables/CORE.Customer"
REVENUE = f"{BRIDGE}/Tables/SALES.Revenue"


def _loadable(identity: str) -> list[dict]:
    parsed = document_id(identity)
    schema, name = parsed.object_id.schema, parsed.object_id.object
    return [
        registry_row(parsed),
        registry_row(
            WeaverDocumentId.parse(
                f"{parsed.item}/file:_/Load/Tables/{schema}__{name}.py"
            ),
            object_type="file",
            object_role="load",
        ),
    ]


def central(result: str = "failed", completed_at=LATER) -> Catalogue:
    item = WeaverItemId.parse(CORE)
    return Catalogue(
        rows={
            item: {
                "Installation": (installation_row(item, "Core_LH"),),
                "Registry": tuple(_loadable(PRODUCER)),
                "LoadStatus": (
                    load_status_row(
                        PRODUCER,
                        result=result,
                        started_at=completed_at,
                        completed_at=completed_at,
                    ),
                ),
            }
        }
    )


def _model_rows() -> dict:
    owner = {"item_type": MODEL.item_type, "item_name": MODEL.item_name}
    root = {**owner, "schema_name": "", "object_name": ""}

    def reads(table: str, producer: str) -> dict:
        parsed = document_id(producer)
        return {
            **owner,
            "referencing_schema_name": "",
            "referencing_object_name": table,
            "dependency_reference": str(parsed),
            "referenced_item_type": parsed.item.item_type,
            "referenced_item_name": parsed.item.item_name,
            "referenced_schema_name": f"Tables/{parsed.object_id.schema}",
            "referenced_object_name": parsed.object_id.object,
        }

    def table(name: str, mode: str) -> dict:
        return {
            **root,
            "table_name": name,
            "source_mode": mode,
            "source_access": "sql",
        }

    return {
        "Installation": (installation_row(MODEL, "Sales_SM"),),
        "Registry": (
            {
                **root,
                "object_type": "semantic_model",
                "object_role": "data",
                "signature": "model",
            },
        ),
        "SemanticModel": ({**root, "signature": "model"},),
        "SemanticModelTable": (
            table("Customer", "directLake"),
            table("Revenue", "import"),
        ),
        "Dependency": (
            reads("Customer", DESTINATION),
            reads("Revenue", REVENUE),
        ),
    }


def _dependency(consumer: str, reference: str) -> dict:
    row = dependency_row(consumer, reference)
    if reference.startswith("shortcuts."):
        # Build records no producer for an imported shortcut.
        row.update(
            referenced_item_type=None,
            referenced_item_name=None,
            referenced_schema_name=None,
            referenced_object_name=None,
        )
    return row


def sales(revenue_loaded=EARLIER, *, reference="CORE.Customer") -> Catalogue:
    bridge = WeaverItemId.parse(BRIDGE)
    shortcut = shortcut_row(
        DESTINATION, "Lakehouse/Core_LH/Tables/CORE.Customer", target_type="physical"
    )
    shortcut["target_workspace_name"] = "Central"
    return Catalogue(
        rows={
            bridge: {
                "Installation": (installation_row(bridge, "Bridge_LH"),),
                "Registry": (
                    registry_row(DESTINATION, object_role="shortcut"),
                    *_loadable(REVENUE),
                ),
                "Shortcut": (shortcut,),
                "Dependency": (_dependency(REVENUE, reference),),
                "LoadStatus": (
                    load_status_row(
                        REVENUE,
                        started_at=revenue_loaded,
                        completed_at=revenue_loaded,
                    ),
                ),
            },
            MODEL: _model_rows(),
        }
    )


def members(producer: Catalogue, consumer: Catalogue) -> list[Member]:
    return [
        Member("Central", "Central", "Weaver", producer, producer.dag()),
        Member("Sales", "Sales", "Weaver", consumer, consumer.dag()),
    ]


@weaver_test()
def test_a_physical_shortcut_joins_two_catalogues():
    joined = join(members(central(), sales()))

    (crossing,) = joined.crossings
    assert crossing.consumer == f"Sales::{DESTINATION}"
    assert crossing.producer == f"Central::{PRODUCER}"
    assert crossing.reason is None
    assert f"Sales::{REVENUE}" in joined.graph.descendants(f"Central::{PRODUCER}")


@weaver_test()
def test_a_shortcut_into_a_catalogue_not_given_is_named_with_a_reason():
    consumer = sales()
    joined = join([Member("Sales", "Sales", "Weaver", consumer, consumer.dag())])

    (crossing,) = joined.crossings
    assert crossing.producer is None
    assert "Central/Lakehouse/Core_LH" in crossing.reason


@weaver_test()
def test_a_failed_central_table_makes_the_consumer_behind():
    report = assess_joined(
        members(central(), sales()), as_of=NOW - timedelta(days=1), generated_at=NOW
    )

    sales_report = next(
        each.report for each in report.catalogues if each.label == "Sales"
    )
    (finding,) = [each for each in sales_report.findings if each.object_id == REVENUE]
    assert finding.code == LOAD_ANCESTOR_UNESTABLISHED
    assert finding.message == f"the last load of Central: {PRODUCER} failed"
    assert "impact" not in report.to_mapping()
    assert "crossings" not in report.to_mapping()


@weaver_test()
def test_a_reloaded_central_table_makes_the_consumer_ready_to_refresh():
    report = assess_joined(
        members(central(result="succeeded", completed_at=LATER), sales()),
        as_of=NOW - timedelta(days=1),
        generated_at=NOW,
    )

    sales_report = next(
        each.report for each in report.catalogues if each.label == "Sales"
    )
    (finding,) = [each for each in sales_report.findings if each.object_id == REVENUE]
    assert finding.code == LOAD_STALE_ANCESTOR


@weaver_test()
def test_a_consumer_loaded_after_the_central_table_is_current():
    report = assess_joined(
        members(
            central(result="succeeded", completed_at=EARLIER),
            sales(revenue_loaded=LATER),
        ),
        as_of=NOW - timedelta(days=1),
        generated_at=NOW,
    )

    sales_report = next(
        each.report for each in report.catalogues if each.label == "Sales"
    )
    assert not [each for each in sales_report.findings if each.object_id == REVENUE]


@weaver_test()
def test_one_catalogue_alone_does_not_see_the_central_failure():
    consumer = sales()
    report = assess_joined(
        [Member("Sales", "Sales", "Weaver", consumer, consumer.dag())],
        as_of=NOW - timedelta(days=1),
        generated_at=NOW,
    )

    (each,) = report.catalogues
    assert not [f for f in each.report.findings if f.object_id == REVENUE]


@weaver_test()
def test_a_python_import_of_the_shortcut_carries_the_failure_across():
    """``from shortcuts import CORE__Customer`` reads the destination, so a
    central failure reaches what the import feeds."""

    consumer = sales(reference="shortcuts.CORE__Customer")
    report = assess_joined(
        members(central(), consumer), as_of=NOW - timedelta(days=1), generated_at=NOW
    )

    sales_report = report.catalogues[1].report
    (finding,) = [each for each in sales_report.findings if each.object_id == REVENUE]
    assert finding.code == LOAD_ANCESTOR_UNESTABLISHED


# --- what is reported, and in what order --------------------------------------


@weaver_test()
def test_catalogues_are_reported_in_the_order_given():
    producer, consumer = central(), sales()
    report = assess_joined(
        [
            Member("Sales", "Sales", "Weaver", consumer, consumer.dag()),
            Member("Central", "Central", "Weaver", producer, producer.dag()),
        ],
        as_of=NOW - timedelta(days=1),
        generated_at=NOW,
    )

    assert [each.label for each in report.catalogues] == ["Sales", "Central"]
    assert [each["label"] for each in report.to_mapping()["catalogues"]] == [
        "Sales",
        "Central",
    ]


@weaver_test()
def test_an_unread_catalogue_keeps_its_place_and_its_readers_are_unverified():
    consumer = sales(revenue_loaded=LATER)
    report = assess_joined(
        [
            Unread("Central", "Central", "Central/Warehouse/Weaver", "refused"),
            Member("Sales", "Sales", "Weaver", consumer, consumer.dag()),
        ],
        as_of=NOW - timedelta(days=1),
        generated_at=NOW,
    )

    first, second = report.catalogues
    assert (first.label, first.report, first.error) == ("Central", None, "refused")
    (finding,) = [each for each in second.report.findings if each.object_id == REVENUE]
    assert finding.code == LOAD_ANCESTOR_UNOBSERVED
    assert finding.severity == AMBER
    assert "Central/Lakehouse/Core_LH" in finding.message
    assert report.status == AMBER
    assert report.to_mapping()["complete"] is False
    assert report.to_mapping()["catalogues"][0]["status"] == AMBER


@weaver_test()
def test_a_catalogue_that_cannot_be_assessed_does_not_stop_the_others(monkeypatch):
    import importlib

    module = importlib.import_module("weaver.health")
    real = module.assess

    def assess(catalogue, **asked):
        if WeaverItemId.parse(CORE) in catalogue.rows:
            raise ValueError("malformed row")
        return real(catalogue, **asked)

    monkeypatch.setattr(module, "assess", assess)
    report = assess_joined(
        members(central(), sales()), as_of=NOW - timedelta(days=1), generated_at=NOW
    )

    first, second = report.catalogues
    assert first.report is None and "malformed row" in first.error
    assert second.report is not None
    assert report.status != GREEN


# --- object graphs across catalogues ------------------------------------------

#: Team A's Raw feeds Team B's live View, which Team A's Summary reads.
A_RAW = "Lakehouse/Alpha/Tables/A.Raw"
A_LIVE = "Lakehouse/Alpha/Tables/B.Live"
A_SUMMARY = "Lakehouse/Alpha/Tables/A.Summary"
B_RAW = "Lakehouse/Beta/Tables/A.Raw"
B_LIVE = "Warehouse/Serving/B.Live"


def _physical(destination: str, target: str, workspace: str) -> dict:
    row = shortcut_row(destination, target, target_type="physical")
    row["target_workspace_name"] = workspace
    return row


def alpha(*, raw=EARLIER, summary=LATER, raw_result="succeeded", reads="B.Live"):
    item = WeaverItemId.parse("Lakehouse/Alpha")
    return Catalogue(
        rows={
            item: {
                "Installation": (installation_row(item, "Alpha_LH"),),
                "Registry": (
                    *_loadable(A_RAW),
                    *_loadable(A_SUMMARY),
                    registry_row(A_LIVE, object_role="shortcut"),
                ),
                "Shortcut": (_physical(A_LIVE, "Warehouse/Serving_WH/B.Live", "Beta"),),
                "Dependency": (_dependency(A_SUMMARY, reads),),
                "LoadStatus": (
                    load_status_row(
                        A_RAW, result=raw_result, started_at=raw, completed_at=raw
                    ),
                    load_status_row(
                        A_SUMMARY, started_at=summary, completed_at=summary
                    ),
                ),
            }
        }
    )


def beta(*, live=EARLIER):
    """Beta shortcuts Alpha's Raw and serves it through the View Live."""

    lake = WeaverItemId.parse("Lakehouse/Beta")
    serving = WeaverItemId.parse("Warehouse/Serving")
    return Catalogue(
        rows={
            lake: {
                "Installation": (installation_row(lake, "Beta_LH"),),
                "Registry": (registry_row(B_RAW, object_role="shortcut"),),
                "Shortcut": (
                    _physical(B_RAW, "Lakehouse/Alpha_LH/Tables/A.Raw", "Alpha"),
                ),
            },
            serving: {
                "Installation": (installation_row(serving, "Serving_WH"),),
                "Registry": (
                    registry_row(B_LIVE, object_type="view"),
                    registry_row(
                        "Warehouse/Serving/A.Raw",
                        object_type="view",
                        object_role="shortcut",
                    ),
                ),
                "Shortcut": (shortcut_row("Warehouse/Serving/A.Raw", B_RAW),),
                "Dependency": (dependency_row(B_LIVE, "A.Raw"),),
                "LoadStatus": (
                    load_status_row(B_LIVE, started_at=live, completed_at=live),
                ),
            },
        }
    )


def _loadable_warehouse(identity: str) -> list[dict]:
    parsed = document_id(identity)
    return [
        registry_row(parsed),
        registry_row(
            WeaverDocumentId.parse(
                f"{parsed.item}/procedure:_/Load {parsed.object_id.qualified}"
            ),
            object_type="stored_procedure",
            object_role="load",
        ),
    ]


def alpha_and_beta(*, raw=EARLIER, summary=LATER, live=EARLIER) -> list[Member]:
    first = alpha(raw=raw, summary=summary)
    second = beta(live=live)
    return [
        Member("Alpha", "Alpha", "Weaver", first, first.dag()),
        Member("Beta", "Beta", "Weaver", second, second.dag()),
    ]


@weaver_test()
def test_reading_back_through_another_catalogue_is_not_a_cycle():
    joined = join(alpha_and_beta())

    assert joined.graph.cycles == ()
    assert f"Alpha::{A_RAW}" in joined.graph.ancestors(f"Alpha::{A_SUMMARY}")


@weaver_test()
def test_a_newer_source_reached_through_another_catalogue_puts_its_reader_behind():
    report = assess_joined(
        alpha_and_beta(raw=LATER, summary=EARLIER, live=NOW - timedelta(days=3)),
        as_of=NOW - timedelta(days=1),
        generated_at=NOW,
    )

    alpha_report = report.catalogues[0].report
    (finding,) = [each for each in alpha_report.findings if each.object_id == A_SUMMARY]
    assert finding.code == LOAD_STALE_ANCESTOR
    assert f"Alpha: {A_RAW}" in finding.message
    assert report.cycles == ()


@weaver_test()
def test_members_of_a_cycle_across_catalogues_are_not_behind_one_another():
    report = assess_joined(
        _cycle_members(summary=EARLIER, live=LATER),
        as_of=NOW - timedelta(days=1),
        generated_at=NOW,
    )

    assert len(report.cycles) == 1
    assert not [
        each
        for each in report.findings
        if each.code in (LOAD_STALE_ANCESTOR, LOAD_ANCESTOR_UNESTABLISHED)
    ]


@weaver_test()
def test_a_failed_member_of_a_cycle_across_catalogues_reaches_the_other():
    report = assess_joined(
        _cycle_members(summary=EARLIER, live=LATER, live_result="failed"),
        as_of=NOW - timedelta(days=1),
        generated_at=NOW,
    )

    (finding,) = [
        each
        for each in report.catalogues[0].report.findings
        if each.object_id == A_SUMMARY
    ]
    assert finding.code == LOAD_ANCESTOR_UNESTABLISHED
    assert finding.message == f"the last load of Beta: {B_LIVE} failed"


def _cycle_members(*, summary, live, live_result="succeeded") -> list[Member]:
    """Alpha's Summary reads Beta's Live, which is loaded from Alpha's Summary."""

    first = alpha(summary=summary)
    lake = WeaverItemId.parse("Lakehouse/Beta")
    serving = WeaverItemId.parse("Warehouse/Serving")
    b_summary = "Lakehouse/Beta/Tables/A.Summary"
    second = Catalogue(
        rows={
            lake: {
                "Installation": (installation_row(lake, "Beta_LH"),),
                "Registry": (registry_row(b_summary, object_role="shortcut"),),
                "Shortcut": (
                    _physical(
                        b_summary, "Lakehouse/Alpha_LH/Tables/A.Summary", "Alpha"
                    ),
                ),
            },
            serving: {
                "Installation": (installation_row(serving, "Serving_WH"),),
                "Registry": (
                    *_loadable_warehouse(B_LIVE),
                    registry_row(
                        "Warehouse/Serving/A.Summary",
                        object_type="view",
                        object_role="shortcut",
                    ),
                ),
                "Shortcut": (shortcut_row("Warehouse/Serving/A.Summary", b_summary),),
                "Dependency": (dependency_row(B_LIVE, "A.Summary"),),
                "LoadStatus": (
                    load_status_row(
                        B_LIVE, result=live_result, started_at=live, completed_at=live
                    ),
                ),
            },
        }
    )
    return [
        Member("Alpha", "Alpha", "Weaver", first, first.dag()),
        Member("Beta", "Beta", "Weaver", second, second.dag()),
    ]


# --- the public operation -----------------------------------------------------


@weaver_test()
def test_health_reads_every_catalogue_and_reports_one_it_cannot_read_in_place(
    monkeypatch,
):
    from support.sessions import given_session

    import weaver
    from weaver.health import Observed
    from weaver.operations import health as operation
    from weaver.workspaces import Workspace

    held = {"Central": central(), "Sales": sales(revenue_loaded=LATER)}

    def read(session, workspace, *, steps=True):
        if workspace.workspace == "Archive":
            raise ConnectionError("the Warehouse refused the connection")
        return held[workspace.workspace], None

    monkeypatch.setattr(operation, "_read", read)
    monkeypatch.setattr(operation, "_observe", lambda *a, **k: Observed())
    import weaver.operations.joined as joined

    monkeypatch.setattr(joined, "retried", lambda work: work())
    session = given_session(workspace=Workspace(workspace="Sales"))

    report = weaver.health(
        catalogue=[
            "Archive/Warehouse/Weaver",
            "Central/Warehouse/Weaver",
            "Sales/Warehouse/Weaver",
        ],
        session=session,
    )

    assert [each.label for each in report.catalogues] == ["Archive", "Central", "Sales"]
    assert "refused the connection" in report.catalogues[0].error
    sales_report = report.catalogues[2].report
    assert LOAD_ANCESTOR_UNESTABLISHED in {
        each.code for each in sales_report.findings if each.object_id == REVENUE
    }
    assert not [call for call in session.calls if "report" in str(call).casefold()]
