"""Wait until a Warehouse can read objects through a Lakehouse's SQL endpoint.

A completed metadata refresh does not mean the endpoint lists a new shortcut
table yet. The Warehouse that reads it asks through its own connection, and
asks Fabric to refresh again while anything is still missing. Fabric can
report a new cross-workspace shortcut as DeltaTableNotFound for minutes before
it syncs, so a reported failure does not end the wait; it explains a timeout.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ...errors import InstallError, WeaverError
from .base import InstallationContext, Waiting

EXECUTOR = "await_endpoint_objects"
TIMEOUT = 600.0
POLL_INTERVAL = 2.0
#: How often a fresh refresh is requested while objects are missing.
REFRESH_INTERVAL = 20.0


class EndpointObjectsExecutor:
    """Waiting state is plain data, because the invocation ledger records it."""

    name = EXECUTOR
    resumable = True
    #: Outlasts the wait, so its own failure names what was never listed and why.
    timeout = TIMEOUT + 60.0

    def execute(
        self, action, payload, context: InstallationContext, state=None
    ) -> dict[str, Any] | Waiting:
        if state is None:
            if payload is None:
                raise InstallError(f"{action.id!r} names no objects to wait for")
            state = {
                "objects": json.loads(payload.decode("utf-8"))["objects"],
                "started": time.monotonic(),
                "refreshed": time.monotonic(),
            }
        missing = _missing(context.sql, state["objects"])
        elapsed = time.monotonic() - state["started"]
        if not missing:
            return {"visible_after_seconds": round(elapsed, 1)}
        if elapsed >= TIMEOUT:
            failed = state.get("failed", {})
            raise InstallError(
                f"the SQL endpoint did not list these tables within {int(TIMEOUT)}s:\n"
                + "\n".join(
                    "  "
                    + name
                    + (f": Fabric reported {failed[name]}" if name in failed else "")
                    for name in (".".join(each) for each in missing)
                )
                + "\nRetry once Fabric has synced them."
            )
        if time.monotonic() - state["refreshed"] >= REFRESH_INTERVAL:
            failed = _refresh(context, missing)
            state = {**state, "refreshed": time.monotonic(), "failed": failed}
        return Waiting({**state, "objects": missing}, POLL_INTERVAL)


def _missing(sql, objects) -> list[list[str]]:
    from ...catalogue.tsql import identifier

    missing = []
    for database in sorted({each[0] for each in objects}):
        listed = {
            (str(row["table_schema"]).casefold(), str(row["table_name"]).casefold())
            for row in sql.query(
                "select table_schema, table_name from "
                f"{identifier(database)}.INFORMATION_SCHEMA.TABLES"
            )
        }
        missing.extend(
            each
            for each in objects
            if each[0] == database
            and (each[1].casefold(), each[2].casefold()) not in listed
        )
    return missing


def _refresh(context, missing) -> dict[str, str]:
    """Ask Fabric to sync what is missing; return the reason for each it could not."""

    from ...targets import ItemRef

    begin = getattr(context.resolver, "start_sql_endpoint_refresh", None)
    if begin is None:
        return {}
    failed = {}
    for database in sorted({each[0] for each in missing}):
        tables = [(schema, name) for one, schema, name in missing if one == database]
        try:
            refresh = begin(ItemRef(database), tables=tables)
        except WeaverError:
            # One already running answers for this one.
            continue
        reported = {
            name.casefold(): reason
            for name, reason in (
                (refresh or {}).get("failed_tables", {})
                if isinstance(refresh, dict)
                else {}
            ).items()
        }
        for schema, name in tables:
            reason = reported.get(f"{schema}.{name}".casefold())
            if reason is not None:
                failed[f"{database}.{schema}.{name}"] = reason
    return failed
