"""Independent result-set boundaries through the real Fabric SQL driver."""

from decimal import Decimal

import pytest
from support.weaver_test import weaver_test

from weaver.sql.errors import SqlExecutionError


@weaver_test(remote=True, resources={"tds"})
def test_fabric_batch_preserves_empty_ordinals_and_original_types(
    ready_warehouse_session, disposable_warehouse
):
    sets = ready_warehouse_session.query_tsql_batch(
        [
            "SELECT CAST(1 AS int) AS [first] WHERE 1=0",
            "SELECT CAST('Table' AS varchar(32)) AS [word], CAST(0 AS bit) AS [enabled]",
            "SELECT CAST(2 AS bigint) AS [third] WHERE 1=0",
            "SELECT CAST(7.25 AS decimal(12,2)) AS [amount], CAST(NULL AS int) AS [missing]",
        ],
        target=disposable_warehouse.target,
    )
    assert sets == (
        (),
        ({"word": "Table", "enabled": False},),
        (),
        ({"amount": Decimal("7.25"), "missing": None},),
    )
    assert sets[1][0]["enabled"] is False
    assert isinstance(sets[3][0]["amount"], Decimal)


@weaver_test(remote=True, resources={"tds"})
def test_fabric_batch_error_does_not_return_partial_rows_or_poison_next_query(
    ready_warehouse_session, disposable_warehouse
):
    with pytest.raises(SqlExecutionError):
        ready_warehouse_session.query_tsql_batch(
            [
                "SELECT 1 AS [first]",
                "SELECT * FROM [__weaver_missing_batch_boundary_43d943__]",
            ],
            target=disposable_warehouse.target,
        )
    assert ready_warehouse_session.query_tsql_batch(
        ["SELECT 9 AS [after_error]"], target=disposable_warehouse.target
    ) == (({"after_error": 9},),)
