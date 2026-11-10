"""Collect endpoint schemas through the catalogue's SQL connection."""

import json

from ...catalogue.column_types import collect_column_types
from ...catalogue.tsql import literal
from ...declaration.metadata import AUDIT_LIVE_DELETE_DATETIME
from ...declaration.model import WeaverItemId
from ...errors import InstallError


class ColumnTypesExecutor:
    name = "column_types"

    def execute(self, action, payload, context):
        spec = json.loads(payload)
        if type(spec["regenerate"]) is not bool:
            raise InstallError(
                "Column inventory requires an explicit regeneration option"
            )
        items = [WeaverItemId.parse(value) for value in spec["items"]]
        scope = (
            " OR ".join(
                f"(d.[Item type] = {literal(item.item_type)} AND d.[Item name] = {literal(item.item_name)})"
                for item in items
            )
            or "1 = 0"
        )
        objects = context.sql.query(
            "SELECT d.[Item type] AS item_type, d.[Item name] AS item_name,\n"
            "d.[Schema name] AS schema_name, d.[Object name] AS object_name,\n"
            "i.[Target name] AS target_name\n"
            "FROM [_].[TableDictionary] d JOIN [_].[Installation] i\n"
            "ON d.[Item type] = i.[Item type] AND d.[Item name] = i.[Item name]\n"
            "INNER JOIN [_].[Registry] r\n"
            "ON d.[Item type] = r.[Item type] AND d.[Item name] = r.[Item name]\n"
            "AND d.[Schema name] = r.[Schema name] AND d.[Object name] = r.[Object name]\n"
            "WHERE LOWER(r.[Object type]) IN ('table', 'view') AND r.[Object role] = 'Data'\n"
            # Spark views are registered but do not exist in a Lakehouse SQL endpoint.
            "AND (d.[Item type] <> 'Lakehouse' OR LOWER(d.[Object type]) = 'table')\n"
            "AND LOWER(d.[Object type]) IN ('table', 'view') AND (" + scope + ")"
        )
        present = context.sql.query(
            "SELECT OBJECT_ID(N'[_].[Mirror]', N'U') AS mirror_id"
        )
        borrowed = (
            context.sql.query(
                "SELECT [Item type] AS item_type, [Item name] AS item_name,\n"
                "[Schema name] AS schema_name, [Object name] AS object_name\n"
                "FROM [_].[Mirror] WHERE [Row delete datetime] = "
                + literal(AUDIT_LIVE_DELETE_DATETIME, "timestamp")
            )
            if present and present[0]["mirror_id"] is not None
            else ()
        )
        return collect_column_types(
            context.sql,
            objects,
            borrowed=borrowed,
            regenerate=spec["regenerate"],
        )
