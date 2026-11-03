"""`weaver execute` against the fixed estate, from a desktop and in Fabric."""

from __future__ import annotations

import pytest
from support.weaver_test import register_session, weaver_test

import weaver
from weaver.errors import ExecuteError
from weaver.operations.execute import ResultSet
from weaver.sessions.program import FabricProgram
from weaver.sessions.run_in_fabric import _workspace_literal

SPARK_SQL = "SET spark.sql.ansi.enabled=true; SELECT id FROM range(5)"


@pytest.fixture
def catalogue_session(weaver_session, fabric_workspace, fabric_catalogue):
    """The shared Session with the catalogue Warehouse's connection acquired."""

    from weaver.targets import ItemRef, WarehouseTarget

    weaver_session.sql_executor(
        WarehouseTarget(ItemRef(fabric_catalogue.name)), workspace=fabric_workspace
    )
    return register_session(weaver_session)


@weaver_test(remote=True, resources={"tds"})
def test_tsql_returns_each_result_set_to_the_limit(catalogue_session, fabric_catalogue):
    weaver_session = catalogue_session
    catalogue = f"Warehouse/{fabric_catalogue.name}"

    result = weaver.execute(
        "tsql",
        catalogue,
        "SELECT TOP 5 name FROM sys.objects ORDER BY name; SELECT 1 AS one",
        limit=2,
        session=weaver_session,
    )
    with pytest.raises(ExecuteError, match="DoesNotExist"):
        weaver.execute(
            "tsql",
            catalogue,
            "SELECT * FROM dbo.DoesNotExist",
            session=weaver_session,
        )

    first, second = result.result_sets
    assert first.columns == ("name",)
    assert len(first.rows) == 2 and first.truncated
    assert second == ResultSet(columns=("one",), rows=((1,),))
    assert result.target == fabric_catalogue.name


@weaver_test(remote=True, resources={"livy"})
def test_spark_sql_and_python_run_in_fabric_with_the_lakehouse_attached(
    weaver_session, fabric_target_lakehouse
):
    sql = weaver.execute(
        "spark-sql", "Lakehouse/Sales", SPARK_SQL, limit=2, session=weaver_session
    )
    printed = weaver.execute(
        "python",
        "Lakehouse/Sales",
        "def main():\n"
        "    print(spark.range(3).count())\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        session=weaver_session,
    )
    with pytest.raises(ExecuteError, match="(?s)before.*ZeroDivisionError"):
        weaver.execute(
            "python",
            "Lakehouse/Sales",
            "print('before')\n1 / 0",
            session=weaver_session,
        )
    with pytest.raises(ExecuteError, match="Spark SQL failed"):
        weaver.execute(
            "spark-sql",
            "Lakehouse/Sales",
            "SELECT * FROM weaver_execute_missing_table",
            session=weaver_session,
        )

    assert sql.target == fabric_target_lakehouse.name
    assert sql.result_sets == (
        ResultSet(columns=("id",), rows=((0,), (1,)), truncated=True),
    )
    assert printed.output == "3\n"


def _hosted_program(workspace, catalogue: str) -> str:
    return (
        "import weaver\n"
        "from weaver.sessions import NotebookSession\n"
        "from weaver.workspaces import *\n"
        f"workspace = {_workspace_literal(workspace)}\n"
        "found = {}\n"
        "with NotebookSession(workspace=workspace, spark=spark) as session:\n"
        "    def run(key, *args, **kwargs):\n"
        "        try:\n"
        "            found[key] = weaver.execute(*args, session=session, **kwargs).to_mapping()\n"
        "        except Exception as exc:\n"
        "            found[key] = {'error': f'{type(exc).__name__}: {exc}'}\n"
        f"    run('spark', 'spark-sql', 'Lakehouse/Sales', {SPARK_SQL!r}, limit=2)\n"
        "    run('python', 'python', 'Lakehouse/Sales', 'print(spark.range(3).count())')\n"
        f"    run('tsql', 'tsql', {catalogue!r}, 'SELECT 1 AS one')\n"
        "emit(found)\n"
    )


@weaver_test(hosted=True, resources={"livy"})
def test_execute_in_a_notebook_matches_the_desktop(
    weaver_session, fabric_workspace, fabric_catalogue
):
    def remote_only():
        raise AssertionError("this must run in Fabric")

    found = weaver_session.execute_python(
        FabricProgram(
            name="execute_in_fabric",
            call=remote_only,
            source=_hosted_program(
                fabric_workspace, f"Warehouse/{fabric_catalogue.name}"
            ),
        ),
        workspace=fabric_workspace,
    )

    assert found["spark"]["result_sets"] == [
        {"columns": ["id"], "rows": [[0], [1]], "truncated": True}
    ], found
    assert found["python"]["output"] == "3\n", found
    assert found["tsql"]["result_sets"] == [
        {"columns": ["one"], "rows": [[1]], "truncated": False}
    ], found


@weaver_test(remote=True, resources={"rest"})
def test_dax_queries_the_fixed_model(
    fabric_workspace_item, fabric_client, fixed_semantic_model_name, rest_session
):
    from weaver.errors import WeaverError
    from weaver.fabric.resources import SEMANTIC_MODEL, find_item

    try:
        find_item(
            fabric_workspace_item,
            fixed_semantic_model_name,
            item_type=SEMANTIC_MODEL,
            client=fabric_client,
        )
    except WeaverError:
        pytest.skip(f"{fixed_semantic_model_name} is not in this workspace")

    result = weaver.execute(
        "dax",
        f"SemanticModel/{fixed_semantic_model_name}",
        'EVALUATE UNION(ROW("Value", 1), ROW("Value", 2))',
        limit=1,
        session=register_session(rest_session),
    )

    assert result.result_sets == (
        ResultSet(columns=("[Value]",), rows=((1,),), truncated=True),
    )
