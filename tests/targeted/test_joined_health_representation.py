"""Health across catalogues: joined where a physical shortcut crosses, assessed
with ancestry through the other catalogue, and each failure's reach listed.

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
    LOAD_ANCESTOR_UNESTABLISHED,
    LOAD_STALE_ANCESTOR,
    assess_joined,
)
from weaver.impact import BEHIND, FROZEN, LIVE

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


def sales(revenue_loaded=EARLIER) -> Catalogue:
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
                "Dependency": (dependency_row(REVENUE, "CORE.Customer"),),
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
def test_a_failed_central_table_makes_the_consumer_behind_and_lists_its_reach():
    report = assess_joined(
        members(central(), sales()), as_of=NOW - timedelta(days=1), generated_at=NOW
    )

    sales_report = next(
        each.report for each in report.catalogues if each.label == "Sales"
    )
    (finding,) = [each for each in sales_report.findings if each.object_id == REVENUE]
    assert finding.code == LOAD_ANCESTOR_UNESTABLISHED
    assert f"Central: {PRODUCER}" in finding.message

    (impact,) = report.impact
    assert (impact.catalogue, impact.object_id) == ("Central", PRODUCER)
    reached = {each.object_id: each for each in impact.affected}
    assert reached[DESTINATION].effect == LIVE
    assert reached[REVENUE].effect == BEHIND
    model = reached[str(WeaverDocumentId.model_root(MODEL))]
    assert model.effect == LIVE
    assert {(t.name, t.effect) for t in model.tables} == {
        ("Customer", LIVE),
        ("Revenue", FROZEN),
    }


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
    assert report.impact == ()


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
    assert report.impact == ()


SHOP_REPORT = WeaverItemId.parse("Report/Shop Overview")
MODEL_GUID = "11111111-2222-3333-4444-555555555555"


def shop() -> Catalogue:
    root = WeaverDocumentId.report_root(SHOP_REPORT)
    return Catalogue(
        rows={
            SHOP_REPORT: {
                "Installation": (installation_row(SHOP_REPORT, "Shop Overview"),),
                "Registry": (registry_row(root, object_type="report"),),
            }
        }
    )


def sales_with_model_guid() -> Catalogue:
    consumer = sales()
    rows = {item: dict(tables) for item, tables in consumer.rows.items()}
    (installation,) = rows[MODEL]["Installation"]
    rows[MODEL]["Installation"] = ({**installation, "item_id": MODEL_GUID},)
    return Catalogue(rows=rows)


@weaver_test()
def test_a_thin_report_in_another_workspace_joins_the_model_it_is_bound_to():
    producer, consumer, thin = central(), sales_with_model_guid(), shop()
    joined_members = [
        *members(producer, consumer),
        Member("Shop", "Shop", "Weaver", thin, thin.dag()),
    ]
    report_node = f"Shop::{WeaverDocumentId.report_root(SHOP_REPORT)}"

    report = assess_joined(
        joined_members,
        as_of=NOW - timedelta(days=1),
        generated_at=NOW,
        report_models={report_node: MODEL_GUID.upper()},
    )

    (impact,) = report.impact
    reached = {(each.catalogue, each.object_id): each for each in impact.affected}
    shop_report = reached[("Shop", str(WeaverDocumentId.report_root(SHOP_REPORT)))]
    assert shop_report.kind == "report"
