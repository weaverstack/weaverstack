"""The ordinary build owns the package catalogue Item lifecycle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from factories import (
    item_bindings,
    lakehouse_table,
    single_document_repository,
    target_inventory,
)
from support.bundles import build_metadata
from support.sessions import given_session
from support.weaver_test import weaver_test
from support.workspaces import WORKSPACE, given_resolver, given_workspace

from weaver.build_bundle import (
    Builder,
    ItemBinding,
    ItemBindings,
    WarehouseBinding,
    build_item_repository,
    effective_item_bindings,
)
from weaver.build_bundle.execution import ExecutionIdentity
from weaver.build_bundle.models import BUILD_TABLE, DROP_TABLE
from weaver.build_bundle.workflow import BuildState
from weaver.catalogue.state import Catalogue
from weaver.catalogue.tables import LINEAGE_TABLES, PROJECTED_TABLES
from weaver.declaration.model import WeaverItemId
from weaver.locations import Location
from weaver.store import FilesystemStore
from weaver.targets import ItemRef

BUILTIN = WeaverItemId.parse("Warehouse/_weaver")


class RecordingExecutor:
    def __init__(self, name: str) -> None:
        self.name = name
        self.seen: list[str] = []
        self.payloads = {}

    def execute(self, action, payload, context):
        self.seen.append(action.id)
        self.payloads[action.id] = payload
        return {"executor": self.name}


@pytest.fixture
def estate(tmp_path):
    """One authored item, and an empty catalogue Warehouse with no `_` at all."""

    root = tmp_path / "repo"
    repository = single_document_repository(
        root,
        item="Lakehouse/Sales",
        documents={"Tables/DWG__Customer.py": lakehouse_table("DWG.Customer")},
    )

    workspace = given_workspace(catalogue="Warehouse/Weaver")
    store = FilesystemStore()
    resolver = given_resolver(workspace=workspace, root=tmp_path)
    for item in ("Weaver", "Sales_LH"):
        store.make_directory(resolver.files_root(ItemRef(item)))
        store.make_directory(resolver.tables_root(ItemRef(item)))

    executors = {
        name: RecordingExecutor(name)
        for name in (
            "spark_sql",
            "spark_sql_batch",
            "spark_schema",
            "spark_table",
            "folder",
            "shortcut",
            "shortcut_readiness",
            "tsql",
            "tsql_batch",
            "load_file",
            "runtime_state",
            "column_types",
            "start_sql_endpoint_table_refresh",
            "await_sql_endpoint_refresh",
            "await_endpoint_objects",
        )
    }
    return {
        "repository": repository,
        "store": store,
        "executors": executors,
        "session": given_session(workspace=workspace, store=store, resolver=resolver),
    }


def _build(estate, *, changed=False):
    """One ordinary build against an entirely empty catalogue."""

    bindings = effective_item_bindings(
        item_bindings(("Lakehouse/Sales", "Sales_LH")),
        control_item=ItemRef("Weaver"),
        workspace_name=WORKSPACE,
    )
    inventories = {
        binding.item: target_inventory(
            target_id=binding.to_bound_target().id,
            target_name=binding.to_bound_target().name,
        )
        for binding in bindings.entries
    }
    catalogue = Catalogue(rows={})
    if changed:
        from weaver.declaration.metadata import TABLE

        catalogue = Catalogue(
            rows={
                item: {
                    name: tuple(
                        dict(row, signature="previous-shape")
                        if name == "Registry" and item != BUILTIN
                        else row
                        for row in rows
                    )
                    for name, rows in tables.items()
                }
                for item, tables in Catalogue.from_repository(
                    estate["repository"]
                ).rows.items()
            }
        )
        inventories = {
            binding.item: target_inventory(
                target_id=binding.to_bound_target().id,
                kind=binding.to_bound_target().kind,
                target_name=binding.to_bound_target().name,
                tables=tuple(
                    identity.object_id.qualified
                    for identity, document in estate[
                        "repository"
                    ].source_documents.items()
                    if identity.item == binding.item and document.kind == TABLE
                ),
                schemas=("_",) if binding.item == BUILTIN else ("DWG",),
            )
            for binding in bindings.entries
        }
    result = build_item_repository(
        estate["repository"],
        bindings=bindings,
        # Nothing persisted, nothing present: the bootstrap state, stated as
        # state rather than arranged by a privileged step.
        state=BuildState(catalogue=catalogue, target_inventories=inventories),
        session=estate["session"],
        executors=estate["executors"],
        source_store=estate["store"],
        catalogue_binding=WarehouseBinding(
            warehouse=ItemRef("Weaver"), workspace_name=WORKSPACE
        ),
    )
    return bindings, result


# --- the built-in item is composed in and bound, without being asked for ------


@weaver_test()
def test_the_repository_carries_the_builtin_item_without_it_being_authored(estate):
    identities = {item.identity for item in estate["repository"].items}

    assert BUILTIN in identities


@weaver_test()
def test_the_builtin_item_is_bound_to_the_catalogue_warehouse_automatically():
    bindings = effective_item_bindings(
        item_bindings(("Lakehouse/Sales", "Sales_LH")),
        control_item=ItemRef("Weaver"),
        workspace_name=WORKSPACE,
    )

    binding = bindings.by_item[BUILTIN]
    assert isinstance(binding.target, WarehouseBinding)
    assert binding.target.warehouse.name == "Weaver"


@weaver_test()
def test_the_catalogue_warehouse_can_also_host_an_authored_item():
    curated = ItemBinding(
        WeaverItemId.parse("Warehouse/Curated"),
        WarehouseBinding(ItemRef("Curated"), workspace_name=WORKSPACE),
    )

    bindings = effective_item_bindings(
        ItemBindings((curated,)),
        control_item=ItemRef("Curated"),
        workspace_name=WORKSPACE,
    )

    assert bindings.by_item[BUILTIN].target.item == curated.target.item
    assert set(bindings.by_item) == {BUILTIN, curated.item}


@weaver_test()
def test_column_inventory_runs_after_registry_publication(estate):
    from weaver.graph import Graph

    _bindings, result = _build(estate)
    actions = [a for _, _, a in result.plan.actions()]
    observed = [a for a in actions if a.executor == "column_types"]
    assert len(observed) == 1
    collector = observed[0]
    graph = Graph(
        (a.id for a in actions), ((dep, a.id) for a in actions for dep in a.depends_on)
    )
    registry = next(a for a in actions if a.kind == "publish_registry")
    dictionaries = next(a for a in actions if a.id == "publish-catalogue")
    assert dictionaries.id in graph.ancestors(collector.id)
    assert registry.id in graph.ancestors(collector.id)
    for action in actions:
        if action.kind == BUILD_TABLE:
            assert action.id in graph.ancestors(collector.id)
    spec = json.loads(estate["executors"]["column_types"].payloads[collector.id])
    assert "Lakehouse/Sales" in spec["items"]
    assert collector.resources == (
        f"warehouse:{next(t.item_id for t in result.plan.targets if t.id == collector.target_id)}",
    )


@weaver_test()
@pytest.mark.parametrize("changed", [False, True])
def test_column_inventory_retains_and_waits_for_lakehouse_endpoint_refresh(
    estate, changed
):
    from weaver.graph import Graph

    _, result = _build(estate, changed=changed)
    actions = [a for _, _, a in result.plan.actions()]
    graph = Graph(
        (a.id for a in actions), ((d, a.id) for a in actions for d in a.depends_on)
    )
    collector = next(a for a in actions if a.executor == "column_types")
    refresh = next(a for a in actions if a.kind == "await_sql_endpoint_refresh")
    visible = next(a for a in actions if a.executor == "await_endpoint_objects")
    assert refresh.id in graph.ancestors(visible.id)
    assert visible.id in graph.ancestors(collector.id)
    started = next(
        a for a in actions if a.executor == "start_sql_endpoint_table_refresh"
    )
    assert started.payload.endswith(".endpoint-tables.json")
    payload = json.loads(estate["executors"][visible.executor].payloads[visible.id])
    assert payload["objects"] == [["Sales_LH", "DWG", "Customer"]]


# --- and the ordinary planner creates the catalogue from nothing --------------


@weaver_test()
def test_an_empty_catalogue_plans_every_catalogue_table_as_an_ordinary_action(estate):
    """The acceptance criterion the nested bootstrap made untestable."""

    _bindings, result = _build(estate)

    built = {
        action.resource_node_id
        for _sequence, _batch, action in result.plan.actions()
        if action.resource_node_id
    }
    for table in PROJECTED_TABLES:
        assert f"{BUILTIN}/{table.qualified}" in built, (
            f"{table.qualified} was not planned by the ordinary build"
        )


@weaver_test()
def test_empty_registry_recovers_existing_protected_catalogue_tables(estate, tmp_path):
    """Inventory protects the physical catalogue even when Registry is empty."""

    repository = estate["repository"]
    bindings = effective_item_bindings(
        item_bindings(("Lakehouse/Sales", "Sales_LH")),
        control_item=ItemRef("Weaver"),
        workspace_name=WORKSPACE,
    )
    bound = {entry.item: entry.to_bound_target() for entry in bindings.entries}
    catalogue_tables = tuple(
        sorted(
            identity.object_id.qualified
            for identity in repository.source_documents
            if identity.item == BUILTIN
        )
    )
    missing = catalogue_tables[-1]
    inventories = {
        item: target_inventory(
            target_id=target.id,
            kind=target.kind,
            target_name=target.name,
            tables=tuple(name for name in catalogue_tables if name != missing)
            if item == BUILTIN
            else (),
            schemas=("_",) if item == BUILTIN else (),
        )
        for item, target in bound.items()
    }
    bundle = Builder(
        repository=repository,
        state=BuildState(catalogue=Catalogue(rows={}), target_inventories=inventories),
        bindings=bindings,
        catalogue_binding=WarehouseBinding(
            warehouse=ItemRef("Weaver"), workspace_name=WORKSPACE
        ),
        source_store=estate["store"],
        execution=ExecutionIdentity(workspace_name=WORKSPACE),
    ).build(output=Location(str(tmp_path / "recovery-bundle")))

    physical = [
        action
        for _sequence, _batch, action in bundle.plan.actions()
        if action.resource_node_id
        and action.resource_node_id.startswith(f"{BUILTIN}/")
        and action.kind in {DROP_TABLE, BUILD_TABLE}
    ]
    assert {(action.kind, action.resource_node_id) for action in physical} == {
        (BUILD_TABLE, f"{BUILTIN}/{missing}"),
        (DROP_TABLE, f"{BUILTIN}/_.ColumnDataType"),
        (BUILD_TABLE, f"{BUILTIN}/_.ColumnDataType"),
    }
    retained = {
        identity
        for identity in build_metadata(bundle.plan).selection.prohibited
        if identity.item == BUILTIN
    }
    assert {identity.object_id.qualified for identity in retained} == set(
        catalogue_tables
    ) - {missing, "_.ColumnDataType"}

    registry = next(
        action
        for _sequence, _batch, action in bundle.plan.actions()
        if action.kind == "publish_registry"
    )
    payload = (
        estate["store"]
        .read(bundle.location.join(*registry.payload.split("/")))
        .decode()
    )
    assert all(
        f"N'_', N'{name.split('.', 1)[1]}'" in payload for name in catalogue_tables
    )


@weaver_test()
def test_a_build_creates_the_graph_tables_an_older_catalogue_lacks(estate, tmp_path):
    repository = estate["repository"]
    bindings = effective_item_bindings(
        item_bindings(("Lakehouse/Sales", "Sales_LH")),
        control_item=ItemRef("Weaver"),
        workspace_name=WORKSPACE,
    )
    bound = {entry.item: entry.to_bound_target() for entry in bindings.entries}
    introduced = {f"_.{table.name}" for table in LINEAGE_TABLES}
    held = tuple(
        sorted(
            identity.object_id.qualified
            for identity in repository.source_documents
            if identity.item == BUILTIN
            and identity.object_id.qualified not in introduced
        )
    )
    inventories = {
        item: target_inventory(
            target_id=target.id,
            kind=target.kind,
            target_name=target.name,
            tables=held if item == BUILTIN else (),
            schemas=("_",) if item == BUILTIN else (),
        )
        for item, target in bound.items()
    }

    bundle = Builder(
        repository=repository,
        state=BuildState(catalogue=Catalogue(rows={}), target_inventories=inventories),
        bindings=bindings,
        catalogue_binding=WarehouseBinding(
            warehouse=ItemRef("Weaver"), workspace_name=WORKSPACE
        ),
        source_store=estate["store"],
        execution=ExecutionIdentity(workspace_name=WORKSPACE),
    ).build(output=Location(str(tmp_path / "upgrade-bundle")))

    created = {
        action.resource_node_id
        for _sequence, _batch, action in bundle.plan.actions()
        if action.resource_node_id
        and action.resource_node_id.startswith(f"{BUILTIN}/")
        and action.kind in {DROP_TABLE, BUILD_TABLE}
    }
    assert created == {
        f"{BUILTIN}/{name}" for name in introduced | {"_.ColumnDataType"}
    }


@weaver_test()
def test_a_graph_failure_is_a_build_warning(estate, tmp_path, monkeypatch):
    import weaver.installed as installed

    real = installed.item_dag

    def failing(catalogue, item):
        if item == WeaverItemId.parse("Lakehouse/Sales"):
            raise RuntimeError("unexpected")
        return real(catalogue, item)

    monkeypatch.setattr(installed, "item_dag", failing)
    bindings = effective_item_bindings(
        item_bindings(("Lakehouse/Sales", "Sales_LH")),
        control_item=ItemRef("Weaver"),
        workspace_name=WORKSPACE,
    )
    inventories = {
        binding.item: target_inventory(
            target_id=binding.to_bound_target().id,
            target_name=binding.to_bound_target().name,
        )
        for binding in bindings.entries
    }
    warned = []

    bundle = Builder(
        repository=estate["repository"],
        state=BuildState(catalogue=Catalogue(rows={}), target_inventories=inventories),
        bindings=bindings,
        catalogue_binding=WarehouseBinding(
            warehouse=ItemRef("Weaver"), workspace_name=WORKSPACE
        ),
        source_store=estate["store"],
        execution=ExecutionIdentity(workspace_name=WORKSPACE),
        warn=warned.append,
    ).build(output=Location(str(tmp_path / "warned-bundle")))

    assert warned == [
        "Lineage for Lakehouse/Sales was not updated: unexpected. The Build continued."
    ]
    published = next(
        action
        for _sequence, _batch, action in bundle.plan.actions()
        if action.kind == "publish_catalogue"
    )
    statements = json.loads(
        estate["store"].read(bundle.location.join(*published.payload.split("/")))
    )
    (graph,) = [line for line in statements if "[_].[LineageNode]" in line]
    assert "N'_weaver'" in graph
    assert "N'Sales'" not in graph


@weaver_test()
def test_the_catalogue_tables_are_built_by_the_same_executors_as_authored_objects(
    estate,
):
    """One installer for built-in and authored artefacts, or the claim is false."""

    _bindings, result = _build(estate)

    catalogue_actions = [
        action
        for _sequence, _batch, action in result.plan.actions()
        if action.resource_node_id and action.resource_node_id.startswith(f"{BUILTIN}/")
    ]
    assert catalogue_actions
    used = {action.executor for action in catalogue_actions}
    assert used <= set(estate["executors"]), (
        f"catalogue work reached an executor authored objects do not use: {used}"
    )


@weaver_test()
def test_the_build_succeeds_against_an_empty_lakehouse_with_no_prior_preparation(
    estate,
):
    _bindings, result = _build(estate)

    assert result.report.status == "succeeded"


# --- setting a project up owns no catalogue lifecycle -------------------------


@weaver_test()
def test_initialise_owns_no_catalogue_ddl_or_publication():
    """`weaver initialise` provisions the Warehouse; the build fills it.

    Source-level, because what it guards is a reintroduced shortcut, and the
    cheapest honest statement of "initialise does not do this" is that its module
    does not name it.
    """

    source = (
        Path(__file__).resolve().parents[2] / "src" / "weaver" / "initialise.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "CREATE TABLE",
        "MERGE INTO",
        "DELETE FROM",
        "generate_item_build_bundle",
        "Installer(",
        "read_reconciled_catalogue",
        "read_target_inventories",
    ):
        assert forbidden not in source, (
            f"initialise.py names {forbidden!r}; the catalogue tables are the "
            "ordinary build's, and setting a project up creates the Warehouse "
            "they live in"
        )
