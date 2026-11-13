"""Catalogue reads retain independent SQL result-set boundaries."""

import pytest
from support.weaver_test import weaver_test

from weaver.catalogue.connection import CatalogueConnection
from weaver.catalogue.reader import read_tables, table_query
from weaver.catalogue.tables import INSTALLATION, REGISTRY, TABLE_DICTIONARY
from weaver.errors import CommandError
from weaver.sessions import ConsoleSession, NotebookSession
from weaver.workspaces import Workspace


@weaver_test()
def test_whole_tables_keep_empty_result_ordinals_and_original_rows():
    calls = []
    tables = (INSTALLATION, REGISTRY, TABLE_DICTIONARY)
    row = {"item_type": "Warehouse", "object_type": "Table", "signature": "v1"}

    def batch(statements):
        calls.append(statements)
        return ((), (row, row), ())

    connection = CatalogueConnection(lambda statement: (), query_sets=batch)
    connection._shape = {
        table.name.casefold(): {
            column.public_name.casefold(): column.public_name
            for column in table.columns
        }
        for table in tables
    }
    result = read_tables(connection, tables)

    assert result[INSTALLATION.name] == ()
    assert result[TABLE_DICTIONARY.name] == ()
    assert len(result[REGISTRY.name]) == 2
    assert result[REGISTRY.name][0]["object_type"] == "table"
    assert result[REGISTRY.name][0]["signature"] == "v1"
    assert calls == [[table_query(connection, table) for table in tables]]


@pytest.mark.parametrize("session_type", [ConsoleSession, NotebookSession])
@weaver_test()
def test_session_batch_uses_one_executor_call_without_merging_result_schemas(
    monkeypatch, session_type
):
    calls = []
    sets = ((), ({"word": "Table", "enabled": False},), ({"amount": 7},))

    class Executor:
        def query_result_sets(self, statement):
            calls.append(statement)
            return sets

    with session_type(workspace=Workspace(workspace="Example")) as session:
        monkeypatch.setattr(session, "sql_executor", lambda *args, **kwargs: Executor())
        result = session.query_tsql_batch(
            ["select 1 where 1=0", "select 'Table', 0", "select 7"], target="unused"
        )
    assert result == sets
    assert calls == ["select 1 where 1=0;\nselect 'Table', 0;\nselect 7;"]


@pytest.mark.parametrize("sets", [(), ((),), ((), (), ())])
@weaver_test()
def test_incorrect_result_set_count_is_not_an_incomplete_catalogue(sets):
    connection = CatalogueConnection(lambda statement: (), query_sets=lambda _: sets)
    with pytest.raises(CommandError, match="result sets"):
        connection.row_sets(["select 1", "select 2"])


@pytest.mark.parametrize("session_type", [ConsoleSession, NotebookSession])
@weaver_test()
def test_session_sets_run_each_query_on_its_own_connection_in_order(
    monkeypatch, session_type
):
    import threading

    statements = ["select 1", "select 2", "select 3"]
    barrier = threading.Barrier(len(statements))

    class Executor:
        def query(self, statement):
            # Every query is in flight at once, or the barrier times out.
            barrier.wait(timeout=5)
            return [{"value": statement}]

    with session_type(workspace=Workspace(workspace="Example")) as session:
        monkeypatch.setattr(session, "sql_executor", lambda *args, **kwargs: Executor())
        result = session.query_tsql_sets(statements, target="unused")
        assert session.query_tsql_sets([], target="unused") == ()
    assert result == tuple(({"value": statement},) for statement in statements)
