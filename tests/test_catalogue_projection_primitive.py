"""A catalogue projection reads typed table rows in one relational request."""

from __future__ import annotations

from datetime import datetime

import pytest
from support.weaver_test import weaver_test

from weaver.catalogue.connection import CatalogueConnection
from weaver.catalogue.reader import read_table, read_tables
from weaver.catalogue.tables import (
    INSTALLATION,
    REGISTRY,
    SEMANTIC_MODEL,
    TABLE_DICTIONARY,
)
from weaver.errors import CommandError


class Transport:
    def __init__(self):
        self.statements = []
        self.responses = []

    def query_tsql(self, statement, **kwargs):
        self.statements.append(statement)
        return [dict(row) for row in self.responses]

    def query_tsql_sets(self, statements, **kwargs):
        return [self.query_tsql(statement, **kwargs) for statement in statements]


def connected(transport, tables=(INSTALLATION, REGISTRY)):
    connection = CatalogueConnection(
        transport.query_tsql, query_sets=transport.query_tsql_sets
    )
    connection._shape = {
        table.name.casefold(): {
            column.public_name.casefold(): column.public_name
            for column in table.columns
        }
        for table in tables
    }
    return connection


@weaver_test()
def test_whole_tables_use_one_relational_read_without_losing_empty_tables():
    transport = Transport()
    rows = read_tables(connected(transport), (INSTALLATION, REGISTRY))

    assert rows == {INSTALLATION.name: (), REGISTRY.name: ()}
    assert len(transport.statements) == 1
    statement = transport.statements[0]
    assert "UNION ALL" in statement
    assert "[_].[Installation]" in statement
    assert "[_].[Registry]" in statement


@weaver_test()
def test_relational_rows_keep_the_single_table_types_vocabulary_and_duplicates():
    moment = datetime(2026, 11, 12, 7, 0)
    raw = {
        "item_type": "Warehouse",
        "item_name": "Orders",
        "schema_name": "Sales",
        "object_name": "Invoice",
        "object_type": "Table",
        "object_role": "Data",
        "signature": "v1",
        "build_datetime": moment,
    }
    reference = connected(Transport())
    reference._query = lambda statement: [dict(raw), dict(raw)]
    expected = read_table(reference, REGISTRY)
    transport = Transport()
    transport.responses = [
        {
            "__weaver_table": 1,
            "c0": "Warehouse",
            "c1": "Orders",
            "c8": "Sales",
            "c9": "Invoice",
            "c10": "Table",
            "c11": "Data",
            "c7": "v1",
            "c12": moment,
        }
    ] * 2

    result = read_tables(connected(transport), (INSTALLATION, REGISTRY))

    assert result == {INSTALLATION.name: (), REGISTRY.name: expected}
    assert len(result[REGISTRY.name]) == 2
    assert transport.responses[0]["c12"] is moment


@pytest.mark.parametrize("ordinal", [-1, 2, True, "1"])
@weaver_test()
def test_unknown_table_tags_fail_instead_of_attaching_rows_to_another_table(ordinal):
    transport = Transport()
    transport.responses = [
        {"__weaver_table": ordinal, **{f"c{i}": None for i in range(13)}}
    ]
    with pytest.raises(CommandError, match="unknown table"):
        read_tables(connected(transport), (INSTALLATION, REGISTRY))


@weaver_test()
def test_interleaved_shared_slots_keep_each_tables_vocabulary_and_false_bits():
    transport = Transport()
    dictionary = {f"c{i}": None for i in range(19)}
    dictionary.update({"__weaver_table": 1, "c4": "Table", "c16": 0, "c17": 1})
    registry = {f"c{i}": None for i in range(19)}
    registry.update({"__weaver_table": 0, "c4": "Table", "c5": "Data"})
    transport.responses = [dictionary, registry, dictionary]
    tables = (REGISTRY, TABLE_DICTIONARY)

    result = read_tables(connected(transport, tables), tables)

    assert result[REGISTRY.name][0]["object_type"] == "table"
    assert len(result[TABLE_DICTIONARY.name]) == 2
    assert result[TABLE_DICTIONARY.name][0]["object_type"] == "Table"
    assert result[TABLE_DICTIONARY.name][0]["is_incremental"] is False
    assert result[TABLE_DICTIONARY.name][0]["is_static"] is True


@weaver_test()
def test_equal_column_names_with_different_widths_keep_distinct_slots():
    transport = Transport()
    dictionary = {f"c{i}": None for i in range(18)}
    dictionary.update({"__weaver_table": 0, "c5": "dictionary"})
    wide = "長" * 7000
    semantic = {f"c{i}": None for i in range(18)}
    semantic.update({"__weaver_table": 1, "c17": wide})
    transport.responses = [semantic, dictionary]
    tables = (TABLE_DICTIONARY, SEMANTIC_MODEL)

    result = read_tables(connected(transport, tables), tables)

    assert result[TABLE_DICTIONARY.name][0]["description"] == "dictionary"
    assert result[SEMANTIC_MODEL.name][0]["description"] == wide
