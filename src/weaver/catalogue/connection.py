"""Read the Weaver catalogue over TDS with one cached schema inventory."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ..errors import CommandError
from .tables import CATALOGUE_SCHEMA
from .tsql import literal


class CatalogueConnection:
    """Catalogue access for one Warehouse; the Session owns transport lifetime."""

    def __init__(
        self,
        query: Callable[[str], Any],
        execute: Callable[[str], Any] | None = None,
        query_sets: Callable[[list[str]], Any] | None = None,
    ) -> None:
        self._query = query
        self._execute = execute
        self._query_sets = query_sets
        self._shape: dict[str, dict[str, str]] | None = None
        self._nullability: dict[str, dict[str, str]] = {}

    # --- the shape of `_` ----------------------------------------------------

    def shape(self) -> Mapping[str, Mapping[str, str]]:
        """Return the cached ``_`` schema under casefolded table and column keys."""

        if self._shape is None:
            found: dict[str, dict[str, str]] = {}
            rows = self._query(
                "SELECT TABLE_NAME, COLUMN_NAME, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS "
                f"WHERE TABLE_SCHEMA = {literal(CATALOGUE_SCHEMA)}"
            )
            for row in rows:
                values = dict(row)
                table = str(values["TABLE_NAME"])
                column = str(values["COLUMN_NAME"])
                found.setdefault(table.casefold(), {})[column.casefold()] = column
                nullable = values.get("IS_NULLABLE")
                if nullable not in {"YES", "NO"}:
                    raise CommandError(
                        f"Catalogue nullability is missing for {table}.{column}"
                    )
                self._nullability.setdefault(table.casefold(), {})[column] = nullable
            self._shape = found
        return self._shape

    def columns_of(self, table) -> dict[str, str] | None:
        """Return columns, or ``None`` when schema inventory shows no table."""

        return self.shape().get(table.name.casefold())

    def nullability_of(self, table) -> dict[str, str]:
        self.shape()
        return self._nullability.get(table.name.casefold(), {})

    def forget_shape(self) -> None:
        """Read the schema again, after a build created or altered a table."""

        self._shape = None
        self._nullability = {}

    # --- reading -------------------------------------------------------------

    def rows(self, statement: str):
        return self._query(statement)

    def row_sets(self, statements: list[str]) -> tuple:
        """Each statement's rows, read together where the transport allows."""

        if self._query_sets is None:
            return tuple(self._query(statement) for statement in statements)
        return tuple(self._query_sets(statements))

    def execute(self, statement: str) -> None:
        if self._execute is None:
            raise CommandError(
                "this catalogue connection is read-only; no statement executor "
                "was provided"
            )
        self._execute(statement)

    def projected_row_sets(self, tables, statements) -> tuple:
        """Read whole catalogue tables through one typed relational projection."""

        from .tsql import identifier

        if not tables:
            return ()
        slots = dict.fromkeys(
            (column.name, column.warehouse_type)
            for table in tables
            for column in table.columns
        )
        slots = {key: f"c{index}" for index, key in enumerate(slots)}
        branches = []
        for ordinal, (table, statement) in enumerate(zip(tables, statements)):
            own = {(column.name, column.warehouse_type) for column in table.columns}
            projection = [f"{ordinal} AS [__weaver_table]"]
            for key, slot in slots.items():
                name, sql_type = key
                value = (
                    f"[source].{identifier(name)}"
                    if key in own
                    else f"CAST(NULL AS {sql_type})"
                )
                projection.append(f"{value} AS {identifier(slot)}")
            branches.append(
                f"SELECT {', '.join(projection)} FROM ({statement}) AS [source]"
            )
        groups = tuple([] for table in tables)
        for row in self.rows(" UNION ALL ".join(branches)):
            ordinal = row["__weaver_table"]
            if type(ordinal) is not int or not 0 <= ordinal < len(tables):
                raise CommandError("Catalogue projection returned an unknown table")
            table = tables[ordinal]
            groups[ordinal].append(
                {
                    column.name: row[slots[column.name, column.warehouse_type]]
                    for column in table.columns
                }
            )
        return groups


def catalogue_connection(session, workspace=None) -> CatalogueConnection:
    """Connect to a Session's configured catalogue Warehouse without Spark."""

    from ..targets import WarehouseTarget

    resolved = session.workspace_or_default(workspace)
    target = WarehouseTarget(warehouse=resolved.catalogue_item)
    return CatalogueConnection(
        lambda statement: session.query_tsql(
            statement, target=target, workspace=resolved
        ),
        lambda statement: session.execute_tsql(
            statement, target=target, workspace=resolved
        ),
        lambda statements: session.query_tsql_sets(
            statements, target=target, workspace=resolved
        ),
    )


__all__ = ["CatalogueConnection", "catalogue_connection"]
