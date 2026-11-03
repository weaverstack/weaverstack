"""The installed graph reads a dependency's producer as Build recorded it.

An object name may contain ``__``, so ``Tables.Sales__Order`` is a relation in
schema ``Tables`` or an import of the ``Tables`` module ``Sales__Order``. The
reference alone cannot say which; the producer Build recorded beside it can.
"""

from __future__ import annotations

import pytest
from factories import (
    installed_catalogue,
    item_bindings,
    lakehouse_table,
    single_document_repository,
    spark_view,
)
from support.weaver_test import weaver_test

from weaver.catalogue.state import Catalogue
from weaver.catalogue.tables import DEPENDENCY
from weaver.declaration.model import WeaverItemId
from weaver.errors import LoadError
from weaver.load_plan import load_dag

ITEM = "Lakehouse/Sales"
SALES = WeaverItemId.parse(ITEM)


def _estate(tmp_path, schema: str, consumers: dict[str, str]):
    """``Sales.Order`` and ``<schema>.Sales__Order``, and the consumers given."""

    repository = single_document_repository(
        tmp_path,
        item=ITEM,
        schemas=("Sales", schema),
        documents={
            "Tables/Sales__Order.py": lakehouse_table("Sales.Order"),
            f"Tables/{schema}__Sales__Order.py": lakehouse_table(
                f"{schema}.Sales__Order"
            ),
            **consumers,
        },
    )
    return installed_catalogue(repository, item_bindings((ITEM, "Sales_LH")))


def _spark_table(object_id: str, *, reads: str) -> str:
    return f"""\
/*
Table ID: {object_id}

Description: A Spark SQL table.

Lineage: {reads}.

Dependencies:
  - {reads}

Schema:
  CustomerId: string
*/
select cast(null as string) as CustomerId from {reads}
 where 1 = 0;
"""


def _importer(object_id: str, module: str, name: str) -> str:
    return lakehouse_table(object_id).replace(
        "from weaver import Table",
        f"from weaver import Table\nfrom {module} import {name}",
    )


def _upstream(catalogue: Catalogue, consumer: str) -> set[str]:
    dag = catalogue.dag()
    assert not dag.unresolved, dag.unresolved
    return {
        str(edge.upstream)
        for edge in dag.edges
        if str(edge.downstream) == f"{ITEM}/Tables/{consumer}"
    }


def _without_recorded_producers(catalogue: Catalogue) -> Catalogue:
    """The rows an estate built before the producer was recorded holds."""

    rows = {item: dict(tables) for item, tables in catalogue.rows.items()}
    for tables in rows.values():
        tables[DEPENDENCY.name] = tuple(
            {
                **row,
                "referenced_item_type": None,
                "referenced_item_name": None,
                "referenced_schema_name": None,
                "referenced_object_name": None,
            }
            for row in tables.get(DEPENDENCY.name, ())
        )
    return Catalogue(rows=rows)


@pytest.mark.parametrize("schema", ["Tables", "Files", "lib"])
@weaver_test()
def test_a_relation_in_a_schema_named_like_an_area_reads_that_schema(tmp_path, schema):
    catalogue = _estate(
        tmp_path,
        schema,
        {
            "Tables/Sales.Report.sql": spark_view(
                "Sales.Report", depends_on=f"{schema}.Sales__Order"
            )
        },
    )

    assert _upstream(catalogue, "Sales.Report") == {
        f"{ITEM}/Tables/{schema}.Sales__Order"
    }


@weaver_test()
def test_an_import_with_the_same_spelling_reads_the_module(tmp_path):
    catalogue = _estate(
        tmp_path,
        "Tables",
        {
            "Tables/Sales__Imported.py": _importer(
                "Sales.Imported", "Tables.Sales__Order", "Sales__Order"
            ),
            "Tables/Sales.Report.sql": spark_view(
                "Sales.Report", depends_on="Tables.Sales__Order"
            ),
        },
    )

    assert _upstream(catalogue, "Sales.Imported") == {f"{ITEM}/Tables/Sales.Order"}
    assert _upstream(catalogue, "Sales.Report") == {
        f"{ITEM}/Tables/Tables.Sales__Order"
    }


@weaver_test()
def test_load_orders_a_relation_in_a_schema_named_like_an_area(tmp_path):
    catalogue = _estate(
        tmp_path,
        "lib",
        {
            "Tables/Sales.Reading.sql": _spark_table(
                "Sales.Reading", reads="lib.Sales__Order"
            ),
        },
    )

    dag = load_dag(catalogue.dag(), items=(SALES,))

    assert (
        "load:Lakehouse/Sales_LH/Tables/lib.Sales__Order",
        "load:Lakehouse/Sales_LH/Tables/Sales.Reading",
    ) in dag.edges


@weaver_test()
def test_an_older_catalogue_still_resolves_ordinary_references(tmp_path):
    catalogue = _without_recorded_producers(
        _estate(
            tmp_path,
            "Tables",
            {
                "Tables/Sales__Imported.py": _importer(
                    "Sales.Imported", "Tables.Sales__Order", "Sales__Order"
                ),
                "Tables/Sales.Report.sql": spark_view(
                    "Sales.Report", depends_on="Sales.Order"
                ),
            },
        )
    )

    assert _upstream(catalogue, "Sales.Imported") == {f"{ITEM}/Tables/Sales.Order"}
    assert _upstream(catalogue, "Sales.Report") == {f"{ITEM}/Tables/Sales.Order"}


@weaver_test()
def test_a_recorded_producer_no_reading_reaches_is_unresolved(tmp_path):
    catalogue = _estate(
        tmp_path,
        "Tables",
        {
            "Tables/Sales.Report.sql": _spark_table(
                "Sales.Report", reads="Tables.Sales__Order"
            )
        },
    )
    rows = {item: dict(tables) for item, tables in catalogue.rows.items()}
    rows[SALES][DEPENDENCY.name] = tuple(
        {**row, "referenced_object_name": "Sales__Missing"}
        if row["dependency_reference"] == "Tables.Sales__Order"
        else row
        for row in rows[SALES][DEPENDENCY.name]
    )
    changed = Catalogue(rows=rows)

    (message,) = changed.dag().unresolved_for(
        next(
            identity
            for identity in changed.dag().unresolved
            if str(identity).endswith("Sales.Report")
        )
    )
    assert "recorded as Lakehouse/Sales/Tables/Tables.Sales__Missing" in message
    with pytest.raises(LoadError, match="Sales__Missing"):
        load_dag(changed.dag(), items=(SALES,))
