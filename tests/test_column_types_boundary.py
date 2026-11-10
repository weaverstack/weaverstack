"""SQL column observations preserve logical identity and complete object scope."""

import importlib.util

import pytest
from support.weaver_test import weaver_test

from weaver.errors import InstallError


@weaver_test()
def test_endpoint_columns_keep_ordinal_type_and_lakehouse_identity():
    assert importlib.util.find_spec("weaver.catalogue.column_types") is not None
    from weaver.catalogue.column_types import observe_columns

    class Endpoint:
        def query(self, statement):
            assert "[Sales endpoint].sys.columns" in statement
            assert "sys.types" in statement
            return [
                {
                    "schema_name": "DWG",
                    "object_name": "Customer",
                    "column_name": "Amount",
                    "column_ordinal": 3,
                    "data_type": "decimal",
                    "max_length": 9,
                    "numeric_precision": 18,
                    "numeric_scale": 2,
                    "is_nullable": True,
                    "is_identity": False,
                    "column_count": 1,
                }
            ]

    objects = [
        {
            "item_type": "Lakehouse",
            "item_name": "Sales",
            "target_name": "Sales endpoint",
            "schema_name": "Tables/DWG",
            "object_name": "Customer",
        }
    ]
    rows = observe_columns(Endpoint(), objects)
    assert len(rows) == 1
    assert rows[0]["schema_name"] == "Tables/DWG"
    assert rows[0]["item_type"] == "Lakehouse"
    assert rows[0]["item_name"] == "Sales"
    assert rows[0]["column_ordinal"] == 3
    assert rows[0]["data_type"] == "decimal(18,2)"
    assert rows[0]["is_nullable"] is True
    assert len(rows[0]["signature"]) == 64


def owner(name="Customer", item="Sales"):
    return {
        "item_type": "Warehouse",
        "item_name": item,
        "schema_name": "DWG",
        "object_name": name,
        "target_name": "Physical",
    }


def column(name="ID", **updates):
    return {
        "schema_name": "DWG",
        "object_name": "Customer",
        "column_name": name,
        "column_ordinal": 1,
        "data_type": "int",
        "max_length": 4,
        "numeric_precision": 10,
        "numeric_scale": 0,
        "is_nullable": False,
        "is_identity": False,
        "column_count": 1,
        **updates,
    }


class SQL:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []
        self.scripts = []

    def query(self, statement):
        self.queries.append(statement)
        if isinstance(self.rows, Exception):
            raise self.rows
        return self.rows

    def execute_script(self, statement):
        self.scripts.append(statement)


@weaver_test()
@pytest.mark.parametrize(
    "borrowed,regenerate,expected",
    [(False, False, 1), (True, False, 0), (True, True, 0)],
)
def test_collection_never_overrides_live_mirrors_during_regeneration(
    borrowed, regenerate, expected
):
    from weaver.catalogue import column_types

    assert hasattr(column_types, "collect_column_types")
    sql = SQL([column()])
    obj = owner()
    mirrors = [obj] if borrowed else []
    result = column_types.collect_column_types(
        sql, [obj], borrowed=mirrors, regenerate=regenerate
    )
    assert result["objects"] == expected
    assert result["columns"] == expected
    assert len(sql.scripts) == expected
    if expected:
        text = sql.scripts[0]
        assert "BEGIN TRANSACTION" in text and "ROLLBACK" in text and "COMMIT" in text
        assert "[Item type] = N'Warehouse'" in text
        assert "[Item name] = N'Sales'" in text
        assert "[Schema name] = N'DWG'" in text
        assert "[Object name] = N'Customer'" in text
        assert "[Column name] NOT IN (N'ID')" in text
        assert "WHEN MATCHED AND" in text
    else:
        assert not sql.queries


@weaver_test()
@pytest.mark.parametrize(
    "rows",
    [
        [],
        [column(column_count=2)],
        [column(), column()],
        RuntimeError("endpoint unavailable"),
    ],
)
def test_failed_or_incomplete_observation_never_writes_inventory(rows):
    from weaver.catalogue import column_types

    assert hasattr(column_types, "collect_column_types")
    sql = SQL(rows)
    with pytest.raises((InstallError, RuntimeError)):
        column_types.collect_column_types(sql, [owner()])
    assert not sql.scripts


@weaver_test()
def test_all_observations_are_checked_before_any_owner_is_changed():
    from weaver.catalogue import column_types

    assert hasattr(column_types, "collect_column_types")
    sql = SQL([column()])
    with pytest.raises(InstallError, match="Missing"):
        column_types.collect_column_types(sql, [owner(), owner("Missing")])
    assert not sql.scripts


@weaver_test()
def test_collection_limits_removals_to_explicit_successful_objects():
    from weaver.catalogue import column_types

    assert hasattr(column_types, "collect_column_types")
    sql = SQL([column("Renamed", column_ordinal=7)])
    column_types.collect_column_types(sql, [owner()])
    text = sql.scripts[0]
    assert "NOT IN (N'Renamed')" in text
    assert "TRUNCATE" not in text
    assert "DROP TABLE" not in text
    assert "N'Other'" not in text


@weaver_test()
@pytest.mark.parametrize("present", [True, False])
def test_mirror_copies_column_inventory_when_present_and_accepts_older_sources(present):
    from weaver.catalogue.fork import FORKED_TABLES, copy_statements, project_source
    from weaver.catalogue.tables import COLUMN_DATA_TYPE

    shape = {
        table.name.casefold(): {name.casefold(): name for name in table.public_columns}
        for table in FORKED_TABLES
        if present or table is not COLUMN_DATA_TYPE
    }
    source = project_source(shape, source="Older catalogue")
    assert (COLUMN_DATA_TYPE.name in source.columns) is present
    statements = copy_statements(source_catalogue="Source catalogue", source=source)
    copies = [s for s in statements if "[ColumnDataType]" in s]
    assert len(copies) == int(present)
    if present:
        assert "from [Source catalogue].[_].[ColumnDataType]" in copies[0]
        for name in COLUMN_DATA_TYPE.public_columns:
            assert "[" + name + "]" in copies[0]
        assert (
            "not ([Item type] = N'Warehouse' and [Item name] = N'_weaver')" in copies[0]
        )


@weaver_test()
def test_executor_selects_only_registered_table_and_view_data_objects():
    import json
    from types import SimpleNamespace

    from weaver.build_bundle.executors.column_types import ColumnTypesExecutor

    class Registered(SQL):
        def query(self, statement):
            self.queries.append(statement)
            if "TableDictionary" in statement:
                assert "INNER JOIN [_].[Registry] r" in statement
                for public in ("Item type", "Item name", "Schema name", "Object name"):
                    assert f"d.[{public}] = r.[{public}]" in statement
                assert "LOWER(r.[Object type]) IN ('table', 'view')" in statement
                assert "r.[Object role] = 'Data'" in statement
                assert (
                    "d.[Item type] <> 'Lakehouse' OR LOWER(d.[Object type]) = 'table'"
                    in statement
                )
                return [owner()]
            if "OBJECT_ID" in statement:
                return [{"mirror_id": None}]
            assert ".sys.columns" in statement
            return [column()]

    sql = Registered([])
    result = ColumnTypesExecutor().execute(
        None,
        json.dumps({"items": ["Warehouse/Sales"], "regenerate": False}),
        SimpleNamespace(sql=sql),
    )
    assert result["objects"] == 1
    assert len(sql.scripts) == 1
    assert not any("FROM [_].[Mirror]" in query for query in sql.queries)


@weaver_test()
def test_rebuilt_inventory_restores_copied_and_unrelated_rows_in_its_build_action():
    from weaver.build_bundle.column_types import preserve_rebuilt_column_inventory
    from weaver.build_bundle.models import BuildBatch, InstallAction
    from weaver.build_bundle.payloads import sha256_hex
    from weaver.build_bundle.stages import BUILD, PlannedStage
    from weaver.catalogue.column_types import observe_columns
    from weaver.catalogue.state import Catalogue
    from weaver.declaration.model import WeaverItemId

    rows = observe_columns(SQL([column()]), [owner()])
    prior = dict(
        rows[0], item_name="Unrelated", is_identity=True, signature="copied-source"
    )
    catalogue = Catalogue(
        rows={WeaverItemId.parse("Warehouse/Unrelated"): {"ColumnDataType": (prior,)}}
    )
    content = b"CREATE TABLE [_].[ColumnDataType] (...);"
    action = InstallAction(
        id="build-columns",
        kind="build_table",
        executor="tsql",
        resource_node_id="Warehouse/_weaver/_.ColumnDataType",
        payload="columns.sql",
        payload_sha256=sha256_hex(content),
    )
    stage = PlannedStage(
        phase=BUILD,
        description="Build",
        payloads={"columns.sql": content},
        batches=(BuildBatch(id="build", target_id="catalogue", actions=(action,)),),
    )
    restored = preserve_rebuilt_column_inventory((stage,), catalogue)[0]
    text = restored.payloads["columns.sql"].decode()
    assert text.startswith(content.decode())
    assert "MERGE INTO [_].[ColumnDataType]" in text
    assert "N'Unrelated'" in text and "N'copied-source'" in text
    assert restored.batches[0].actions[0].payload_sha256 == sha256_hex(text.encode())


@weaver_test()
def test_catalogue_build_carries_unselected_inventory_without_certifying_its_owner():
    from weaver.catalogue.column_types import observe_columns
    from weaver.catalogue.state import read_catalogue_state
    from weaver.declaration.model import WeaverItemId

    prior = dict(observe_columns(SQL([column()]), [owner()])[0], item_name="Unrelated")

    class Connection:
        def __init__(self):
            self.queries = []

        def columns_of(self, table):
            return {name.casefold(): name for name in table.public_columns}

        def nullability_of(self, table):
            return {name: "NO" for name in table.public_columns}

        def rows(self, statement):
            self.queries.append(statement)
            return (
                [prior]
                if "FROM [_].[ColumnDataType]" in statement
                and " WHERE " not in statement
                else []
            )

    sql = Connection()
    state = read_catalogue_state(sql, (WeaverItemId.parse("Warehouse/_weaver"),))
    assert state.rows[WeaverItemId.parse("Warehouse/Unrelated")]["ColumnDataType"] == (
        prior,
    )
    assert not state.registered
    assert sum("FROM [_].[ColumnDataType]" in q for q in sql.queries) == 1


@weaver_test()
def test_physical_reconciliation_keeps_last_columns_until_successful_observation():
    from factories import target_inventory

    from weaver.catalogue.column_types import observe_columns
    from weaver.catalogue.state import Catalogue, reconcile_catalogue_state
    from weaver.declaration.model import WeaverItemId

    item = WeaverItemId.parse("Warehouse/Sales")
    prior = observe_columns(SQL([column()]), [owner()])
    registered = {
        name: owner()[name]
        for name in ("item_type", "item_name", "schema_name", "object_name")
    }
    registered.update(object_type="table", object_role="data", signature="old")
    state = Catalogue(rows={item: {"Registry": (registered,), "ColumnDataType": prior}})
    absent = target_inventory(
        target_id="sales", kind="warehouse", target_name="Physical", tables=()
    )
    result = reconcile_catalogue_state(state, inventories={item: absent})
    assert result.catalogue.rows[item]["ColumnDataType"] == prior
    assert any(
        claim.rule.table.name == "ColumnDataType" for claim in result.stale_claims
    )
