"""Observe complete SQL-endpoint schemas without reading user rows."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from ..errors import InstallError
from .claims import stored_area
from .tsql import identifier, literal

IDENTITY = ("item_type", "item_name", "schema_name", "object_name")


def object_key(row):
    return tuple(row[name] for name in IDENTITY)


def _physical_schema(row):
    return stored_area(row["schema_name"])[1]


def metadata_query(database, objects):
    prefix = identifier(database) + ".sys."
    selected = " OR ".join(
        f"(s.name = {literal(_physical_schema(row))} AND o.name = {literal(row['object_name'])})"
        for row in objects
    )
    if not selected:
        raise ValueError("Column observation requires an explicit object scope")
    return (
        "SELECT s.name AS schema_name, o.name AS object_name, c.name AS column_name,\n"
        "c.column_id AS column_ordinal, t.name AS data_type, c.max_length AS max_length,\n"
        "c.precision AS numeric_precision, c.scale AS numeric_scale,\n"
        "c.is_nullable AS is_nullable, c.is_identity AS is_identity,\n"
        "COUNT_BIG(*) OVER (PARTITION BY c.object_id) AS column_count\n"
        f"FROM {prefix}columns c\n"
        f"JOIN {prefix}objects o ON o.object_id = c.object_id\n"
        f"JOIN {prefix}schemas s ON s.schema_id = o.schema_id\n"
        f"JOIN {prefix}types t ON t.user_type_id = c.user_type_id\n"
        f"WHERE o.type IN ('U', 'V') AND ({selected})\n"
        "ORDER BY s.name, o.name, c.column_id"
    )


def sql_type(row):
    name = row["data_type"]
    kind = name.casefold()
    if kind in {"varchar", "char", "varbinary", "binary", "nvarchar", "nchar"}:
        width = row["max_length"]
        if width == -1:
            return name + "(max)"
        if kind in {"nvarchar", "nchar"}:
            width //= 2
        return f"{name}({width})"
    if kind in {"decimal", "numeric"}:
        return f"{name}({row['numeric_precision']},{row['numeric_scale']})"
    if kind in {"datetime2", "datetimeoffset", "time"}:
        return f"{name}({row['numeric_scale']})"
    return name


def observe_columns(sql, objects):
    """Refuse missing or incomplete objects before the caller writes anything."""
    targets = defaultdict(list)
    for row in objects:
        targets[row["target_name"]].append(row)
    observed = []
    for database, wanted in sorted(targets.items()):
        found = defaultdict(list)
        for row in sql.query(metadata_query(database, wanted)):
            found[(row["schema_name"], row["object_name"])].append(row)
        for owner in wanted:
            label = f"{owner['item_type']}/{owner['item_name']}/{owner['schema_name']}.{owner['object_name']}"
            columns = found.get((_physical_schema(owner), owner["object_name"]), [])
            if not columns:
                raise InstallError(
                    f"{label}: SQL endpoint returned no columns; prior column inventory retained"
                )
            counts = {row["column_count"] for row in columns}
            names = {row["column_name"] for row in columns}
            ordinals = {row["column_ordinal"] for row in columns}
            if (
                counts != {len(columns)}
                or len(names) != len(columns)
                or len(ordinals) != len(columns)
            ):
                raise InstallError(
                    f"{label}: incomplete SQL column inventory; prior inventory retained"
                )
            for column in sorted(columns, key=lambda row: row["column_ordinal"]):
                row = {name: owner[name] for name in IDENTITY}
                row.update(
                    {
                        name: column[name]
                        for name in (
                            "column_name",
                            "column_ordinal",
                            "data_type",
                            "max_length",
                            "numeric_precision",
                            "numeric_scale",
                            "is_nullable",
                            "is_identity",
                        )
                    }
                )
                if (
                    row["column_ordinal"] < 1
                    or not row["column_name"]
                    or not row["data_type"]
                    or row["is_nullable"] not in (True, False, 0, 1)
                ):
                    raise InstallError(
                        f"{label}: invalid SQL column metadata; prior inventory retained"
                    )
                row["is_nullable"] = bool(row["is_nullable"])
                row["is_identity"] = (
                    None if row["is_identity"] is None else bool(row["is_identity"])
                )
                row["data_type"] = sql_type(row)
                row["signature"] = hashlib.sha256(
                    json.dumps(row, sort_keys=True).encode()
                ).hexdigest()
                observed.append(row)
    return tuple(observed)


def collect_column_types(sql, objects, *, borrowed=(), regenerate=False):
    """Reconcile observed objects atomically; live mirrors retain copied rows."""
    from .render import InstallationScope, render_merge
    from .tables import COLUMN_DATA_TYPE

    borrowed_keys = {object_key(row) for row in borrowed}
    selected = [row for row in objects if object_key(row) not in borrowed_keys]
    keys = [object_key(row) for row in selected]
    if len(keys) != len(set(keys)):
        raise InstallError("Column inventory names an object more than once")
    rows = observe_columns(sql, selected)
    by_object = defaultdict(list)
    for row in rows:
        by_object[object_key(row)].append(row)
    statements = []
    for obj in selected:
        owned = by_object[object_key(obj)]
        predicate = " AND ".join(
            f"{identifier(COLUMN_DATA_TYPE.public_name_of(name))} = {literal(obj[name])}"
            for name in IDENTITY
        )
        names = ", ".join(literal(row["column_name"]) for row in owned)
        statements.append(
            "DELETE FROM [_].[ColumnDataType] WHERE "
            + predicate
            + " AND [Column name] NOT IN ("
            + names
            + ");"
        )
        statements.append(
            render_merge(
                COLUMN_DATA_TYPE,
                owned,
                scope=InstallationScope(obj["item_type"], obj["item_name"]),
            )
        )
    if statements:
        sql.execute_script(
            "BEGIN TRY\nBEGIN TRANSACTION;\n"
            + "\n".join(statements)
            + "\nCOMMIT;\nEND TRY\nBEGIN CATCH\nIF @@TRANCOUNT > 0 ROLLBACK;\nTHROW;\nEND CATCH;"
        )
    return {
        "objects": len(selected),
        "columns": len(rows),
        "borrowed": len(objects) - len(selected),
    }
