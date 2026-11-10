"""Column inventory against real SQL, without rebuilding the estate per case.

Use an empty Warehouse (WEAVER_PYTEST_WAREHOUSE overrides the suite's target).
One ordinary Build bootstraps it; the cases then change only test-owned SQL.
"""

import json
from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest
from support.weaver_test import register_session, weaver_test

import weaver
from weaver.build_bundle.executors.column_types import ColumnTypesExecutor
from weaver.catalogue.fork import create_statement
from weaver.catalogue.render import InstallationScope, render_merge
from weaver.catalogue.tables import MIRROR
from weaver.sessions import ConsoleSession


@dataclass
class Estate:
    sql: object
    workspace: object
    path: object
    target: str

    def collect(self, *, regenerate=False):
        return ColumnTypesExecutor().execute(
            None,
            json.dumps({"items": ["Warehouse/Columns"], "regenerate": regenerate}),
            SimpleNamespace(sql=self.sql),
        )

    def inventory(self, name="RegisteredView"):
        return self.sql.query(
            "SELECT [Column name] AS name, [Column ordinal] AS ordinal, "
            "[Data type] AS datatype, [Row update datetime] AS updated "
            "FROM [_].[ColumnDataType] WHERE [Item type] = N'Warehouse' "
            "AND [Item name] = N'Columns' AND [Schema name] = N'ColumnTest' "
            "AND [Object name] = N'" + name + "' ORDER BY [Column ordinal]"
        )

    def build(self, *, expected_success=True):
        with ConsoleSession(workspace=self.workspace, progress=False) as session:
            register_session(session)
            result = weaver.build(str(self.path), items=[self.target], session=session)
        assert result.succeeded is expected_success, [
            failure.describe() for failure in result.errors
        ]
        return result


@pytest.fixture(scope="module")
def shared_column_estate(
    fabric_workspace, session_disposable_warehouse, tmp_path_factory
):
    sql = session_disposable_warehouse.executor
    if sql.query("SELECT SCHEMA_ID(N'_') AS existing")[0]["existing"] is not None:
        pytest.skip(
            "Column inventory boundary needs an empty Warehouse; set WEAVER_PYTEST_WAREHOUSE"
        )
    name = session_disposable_warehouse.item.name
    own = replace(fabric_workspace, catalogue=f"Warehouse/{name}")
    root = tmp_path_factory.mktemp("column-inventory")
    table = root / "Warehouse" / "Columns" / "ColumnTest.Registered.sql"
    table.parent.mkdir(parents=True)
    table.write_text(
        """/*
Table ID: ColumnTest.Registered
Description: A table owned by the column inventory boundary test.
Lineage: Constant test fields.
Primary key: ID
*/
select cast(1 as bigint) as ID, cast('test' as varchar(100)) as Name
""",
        encoding="utf-8",
    )
    table.with_name("ColumnTest.RegisteredView.sql").write_text(
        """/*
View ID: ColumnTest.RegisteredView
Description: A registered view owned by the column inventory boundary test.
Lineage: ColumnTest.Registered.
*/
select ID, Name from ColumnTest.Registered
""",
        encoding="utf-8",
    )
    estate = Estate(sql, own, root, f"Warehouse/Columns=Warehouse/{name}")
    # The same target owns the catalogue and user schemas; avoid two independent
    # create-schema stages racing the initial underscore schema.
    sql.execute_script("create schema [_];")
    try:
        estate.build()
        yield estate
    finally:
        from test_catalogue_upgrade_boundary import _forget_the_catalogue_schema

        sql.execute_script("drop view if exists [ColumnTest].[RegisteredView];")
        sql.execute_script(
            "drop table if exists [ColumnTest].[Registered]; drop table if exists [ColumnTest].[AdminExtra];"
        )
        sql.execute_script(
            "if schema_id(N'ColumnTest') is not null exec('drop schema [ColumnTest]');"
        )
        _forget_the_catalogue_schema(sql)
        assert sql.query("SELECT SCHEMA_ID(N'_') AS existing")[0]["existing"] is None


@pytest.fixture
def column_estate(shared_column_estate, warehouse_session):
    register_session(warehouse_session)
    return shared_column_estate


@weaver_test(remote=True, resources={"tds"})
def test_sql_inventory_is_complete_and_noop_refresh_preserves_audit_times(
    column_estate,
):
    before = column_estate.inventory()
    assert [row["name"] for row in before] == ["ID", "Name"]
    assert [row["datatype"] for row in before] == ["bigint", "varchar(100)"]
    result = column_estate.collect()
    assert result["objects"] == 2
    assert result["columns"] == 8  # Table audit fields are SQL-visible columns too.
    assert column_estate.inventory() == before


@weaver_test(remote=True, resources={"tds"})
def test_unregistered_admin_tables_do_not_enter_inventory(column_estate):
    from weaver.catalogue.tables import TABLE_DICTIONARY
    from weaver.catalogue.tsql import identifier, literal

    sql = column_estate.sql
    sql.execute_script("create table [ColumnTest].[AdminExtra] ([Noise] bigint);")
    columns = ", ".join(identifier(name) for name in TABLE_DICTIONARY.public_columns)
    source = ", ".join(
        literal("AdminExtra") if name == "Object name" else identifier(name)
        for name in TABLE_DICTIONARY.public_columns
    )
    # A dictionary row alone is not certification: Registry is the authority.
    sql.execute_script(
        "insert into [_].[TableDictionary] ("
        + columns
        + ") select "
        + source
        + " from [_].[TableDictionary] where [Item name]=N'Columns' and [Object name]=N'Registered';"
    )
    try:
        result = column_estate.collect()
        assert result["objects"] == 2
        assert not column_estate.inventory("AdminExtra")
    finally:
        sql.execute_script(
            "delete from [_].[TableDictionary] where [Item name]=N'Columns' and [Object name]=N'AdminExtra'; drop table [ColumnTest].[AdminExtra];"
        )


@weaver_test(remote=True, resources={"tds"})
def test_changed_view_reconciles_order_type_additions_and_removals(column_estate):
    sql = column_estate.sql
    try:
        sql.execute_script(
            "create or alter view [ColumnTest].[RegisteredView] as select Name, ID, cast(1 as decimal(18,2)) as Added from [ColumnTest].[Registered];"
        )
        column_estate.collect()
        actual = column_estate.inventory()
        assert [(r["name"], r["ordinal"], r["datatype"]) for r in actual] == [
            ("Name", 1, "varchar(100)"),
            ("ID", 2, "bigint"),
            ("Added", 3, "decimal(18,2)"),
        ]
        sql.execute_script(
            "create or alter view [ColumnTest].[RegisteredView] as select ID from [ColumnTest].[Registered];"
        )
        column_estate.collect()
        assert [row["name"] for row in column_estate.inventory()] == ["ID"]
        assert [row["name"] for row in column_estate.inventory("Registered")] == [
            "ID",
            "Name",
            "Row insert datetime",
            "Row update datetime",
            "Row delete datetime",
            "Row signature",
        ]
    finally:
        sql.execute_script(
            "create or alter view [ColumnTest].[RegisteredView] as select ID, Name from [ColumnTest].[Registered];"
        )
        column_estate.collect()


@weaver_test(remote=True, resources={"tds"})
def test_live_mirror_keeps_copied_inventory_and_retired_mirror_collects_locally(
    column_estate,
):
    sql = column_estate.sql
    sql.execute_script(create_statement(MIRROR))
    row = {
        "item_type": "Warehouse",
        "item_name": "Columns",
        "schema_name": "ColumnTest",
        "object_name": "RegisteredView",
        "source_workspace_name": column_estate.workspace.workspace,
        "source_target_name": "source",
        "source_schema_name": "ColumnTest",
        "source_object_name": "RegisteredView",
        "physical_type": "view",
    }
    sql.execute_script(
        render_merge(MIRROR, [row], scope=InstallationScope("Warehouse", "Columns"))
    )
    before = column_estate.inventory()
    try:
        sql.execute_script(
            "create or alter view [ColumnTest].[RegisteredView] as select ID from [ColumnTest].[Registered];"
        )
        assert column_estate.collect()["borrowed"] == 1
        assert column_estate.inventory() == before
        sql.execute_script(
            "update [_].[Mirror] set [Row delete datetime] = sysdatetime() where [Item name]=N'Columns';"
        )
        assert column_estate.collect()["borrowed"] == 0
        assert [row["name"] for row in column_estate.inventory()] == ["ID"]
    finally:
        sql.execute_script("drop table [_].[Mirror];")
        sql.execute_script(
            "create or alter view [ColumnTest].[RegisteredView] as select ID, Name from [ColumnTest].[Registered];"
        )
        column_estate.collect()


@weaver_test(remote=True, resources={"tds"})
def test_missing_registered_object_preserves_all_prior_inventory(column_estate):
    from weaver.errors import InstallError

    sql = column_estate.sql
    before = column_estate.inventory()
    table_before = column_estate.inventory("Registered")
    sql.execute_script("drop view [ColumnTest].[RegisteredView];")
    try:
        with pytest.raises(InstallError, match="no columns"):
            column_estate.collect()
        assert column_estate.inventory() == before
        assert column_estate.inventory("Registered") == table_before
    finally:
        sql.execute_script(
            "create or alter view [ColumnTest].[RegisteredView] as select ID, Name from [ColumnTest].[Registered];"
        )
        column_estate.collect()


@weaver_test(remote=True, resources={"rest", "tds"})
def test_normal_build_adds_missing_inventory_and_can_rebuild_it(column_estate):
    sql = column_estate.sql
    registered = sql.query("select count(*) as n from [_].[Registry]")[0]["n"]
    physical = sql.query("select object_id(N'ColumnTest.Registered') as id")[0]["id"]
    sql.execute_script(
        "drop table [_].[ColumnDataType]; delete from [_].[Registry] where [Item type]=N'Warehouse' and [Item name]=N'_weaver' and [Object name]=N'ColumnDataType';"
    )
    column_estate.build()
    assert [r["name"] for r in column_estate.inventory()] == ["ID", "Name"]
    assert sql.query("select count(*) as n from [_].[Registry]")[0]["n"] == registered
    assert (
        sql.query("select object_id(N'ColumnTest.Registered') as id")[0]["id"]
        == physical
    )
    inventory_id = sql.query("select object_id(N'_.ColumnDataType') as id")[0]["id"]
    sql.execute_script(
        "delete from [_].[Registry] where [Item type]=N'Warehouse' and [Item name]=N'_weaver' and [Object name]=N'ColumnDataType';"
    )
    column_estate.build()
    assert (
        sql.query("select object_id(N'_.ColumnDataType') as id")[0]["id"]
        != inventory_id
    )
    assert [r["name"] for r in column_estate.inventory()] == ["ID", "Name"]
    assert (
        sql.query("select object_id(N'ColumnTest.Registered') as id")[0]["id"]
        == physical
    )


@weaver_test(remote=True, resources={"rest", "tds"})
@pytest.mark.parametrize("fail_observation", [False, True])
def test_rebuild_retains_live_mirror_and_unrelated_inventory_even_if_observation_fails(
    column_estate, monkeypatch, fail_observation
):
    from weaver.catalogue import column_types
    from weaver.catalogue.tables import COLUMN_DATA_TYPE
    from weaver.catalogue.tsql import identifier
    from weaver.errors import InstallError

    sql = column_estate.sql
    sql.execute_script(create_statement(MIRROR))
    mirror = {
        "item_type": "Warehouse",
        "item_name": "Columns",
        "schema_name": "ColumnTest",
        "object_name": "RegisteredView",
        "source_workspace_name": column_estate.workspace.workspace,
        "source_target_name": "source",
        "source_schema_name": "ColumnTest",
        "source_object_name": "RegisteredView",
        "physical_type": "view",
    }
    sql.execute_script(
        render_merge(MIRROR, [mirror], scope=InstallationScope("Warehouse", "Columns"))
    )
    sql.execute_script(
        "update [_].[ColumnDataType] set [Is identity]=1, [Signature]=replicate('c',64) where [Item name]=N'Columns' and [Object name]=N'RegisteredView';"
    )
    public = ", ".join(identifier(name) for name in COLUMN_DATA_TYPE.public_columns)
    source = ", ".join(
        "N'Unrelated'" if name == "Item name" else identifier(name)
        for name in COLUMN_DATA_TYPE.public_columns
    )
    sql.execute_script(
        f"insert into [_].[ColumnDataType] ({public}) select {source} from [_].[ColumnDataType] where [Item name]=N'Columns' and [Object name]=N'RegisteredView';"
    )
    business = ", ".join(
        identifier(COLUMN_DATA_TYPE.public_name_of(name))
        for name in COLUMN_DATA_TYPE.column_names
    )

    def retained():
        return sql.query(
            f"select {business} from [_].[ColumnDataType] where [Item name]=N'Unrelated' or ([Item name]=N'Columns' and [Object name]=N'RegisteredView') order by [Item name], [Column ordinal];"
        )

    before = retained()
    inventory_id = sql.query("select object_id(N'_.ColumnDataType') as id")[0]["id"]
    original = column_types.observe_columns

    def observation(sql, objects):
        assert all(
            obj["item_name"] != "Unrelated" and obj["object_name"] != "RegisteredView"
            for obj in objects
        )
        if fail_observation:
            raise InstallError("injected inventory observation failure")
        return original(sql, objects)

    try:
        sql.execute_script(
            "delete from [_].[Registry] where [Item name]=N'_weaver' and [Object name]=N'ColumnDataType';"
        )
        with monkeypatch.context() as patch:
            patch.setattr(column_types, "observe_columns", observation)
            result = column_estate.build(expected_success=not fail_observation)
        if fail_observation:
            assert any(
                "injected inventory observation failure" in failure.describe()
                for failure in result.errors
            )
        assert (
            sql.query("select object_id(N'_.ColumnDataType') as id")[0]["id"]
            != inventory_id
        )
        assert retained() == before
    finally:
        sql.execute_script(
            "drop table [_].[Mirror]; delete from [_].[ColumnDataType] where [Item name]=N'Unrelated';"
        )
        column_estate.collect()
