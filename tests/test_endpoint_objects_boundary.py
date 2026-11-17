"""A Warehouse waits until a Lakehouse's SQL endpoint lists what it will read.

A completed metadata refresh does not mean the endpoint already lists a new
shortcut table, so the reader asks through its own connection.
"""

from __future__ import annotations

import json

import pytest
from support.weaver_test import weaver_test

from weaver.build_bundle.executors import endpoint_objects
from weaver.build_bundle.executors.base import InstallationContext, Waiting
from weaver.build_bundle.executors.endpoint_objects import EndpointObjectsExecutor
from weaver.errors import InstallError

PAYLOAD = json.dumps(
    {"objects": [["Input_Dev", "Sales", "Customer"], ["Input_Dev", "Sales", "Order"]]}
).encode()


class _Endpoint:
    """Lists what it has been told it lists, case as Fabric happens to say it."""

    def __init__(self, *listed):
        self.listed = list(listed)
        self.asked = []

    def query(self, statement):
        self.asked.append(statement)
        return [{"table_schema": s, "table_name": n} for s, n in self.listed]


class _Resolver:
    """Fabric's refresh, answering with the tables each sync could not reach."""

    def __init__(self, *failures):
        self.refreshed = []
        self.failures = list(failures)

    def start_sql_endpoint_refresh(self, item, *, tables=None):
        self.refreshed.append((item.name, tables))
        failed = self.failures.pop(0) if self.failures else {}
        return {"done": True, "failed_tables": failed}


def _context(sql, resolver=None):
    return InstallationContext(
        resolver=resolver or _Resolver(), store=None, target=None, sql=sql
    )


@weaver_test()
def test_the_wait_ends_once_every_object_is_listed():
    endpoint = _Endpoint(("sales", "customer"))
    context = _context(endpoint)
    executor = EndpointObjectsExecutor()

    waiting = executor.execute(None, PAYLOAD, context)
    assert isinstance(waiting, Waiting)
    assert waiting.state["objects"] == [["Input_Dev", "Sales", "Order"]]

    endpoint.listed.append(("Sales", "Order"))
    done = executor.execute(None, None, context, state=waiting.state)

    assert "visible_after_seconds" in done
    assert all("[Input_Dev].INFORMATION_SCHEMA.TABLES" in s for s in endpoint.asked)


@weaver_test()
def test_a_missing_object_asks_fabric_to_sync_it_again(monkeypatch):
    resolver = _Resolver()
    context = _context(_Endpoint(), resolver)
    executor = EndpointObjectsExecutor()
    monkeypatch.setattr(endpoint_objects, "REFRESH_INTERVAL", 0.0)

    executor.execute(None, PAYLOAD, context)

    assert resolver.refreshed == [
        ("Input_Dev", [("Sales", "Customer"), ("Sales", "Order")])
    ]


@weaver_test()
def test_an_object_never_listed_fails_by_name(monkeypatch):
    context = _context(_Endpoint(("Sales", "Customer")))
    executor = EndpointObjectsExecutor()
    monkeypatch.setattr(endpoint_objects, "TIMEOUT", 0.0)

    with pytest.raises(InstallError, match=r"Input_Dev\.Sales\.Order"):
        executor.execute(None, PAYLOAD, context)


@weaver_test()
def test_only_what_an_endpoint_lists_is_waited_for():
    """An endpoint lists Lakehouse tables and table shortcuts, never Spark views."""

    from types import SimpleNamespace

    from weaver.build_bundle.shortcuts import _endpoint_lists
    from weaver.declaration.metadata import TABLE, VIEW

    table, view, pointer, folder = (
        f"Lakehouse/Sales/Tables/Sales.{name}"
        for name in ("Customer", "Recent", "Order", "Drop")
    )

    def shortcut(destination, **form):
        flags = {"is_files": False, "is_view": False, "is_schema": False, **form}
        return SimpleNamespace(destination=destination, **flags)

    repository = SimpleNamespace(
        source_documents={
            table: SimpleNamespace(kind=TABLE),
            view: SimpleNamespace(kind=VIEW),
        },
        shortcuts=(shortcut(pointer), shortcut(folder, is_files=True)),
    )

    assert _endpoint_lists(repository, table)
    assert not _endpoint_lists(repository, view)
    assert _endpoint_lists(repository, pointer)
    assert not _endpoint_lists(repository, folder)


NOT_FOUND = (
    "DeltaTableNotFound: Delta table 'Tables\\Sales\\Order\\_delta_log' not found."
)


def _waits(executor, context, state):
    result = executor.execute(None, None, context, state=state)
    assert isinstance(result, Waiting)
    return result.state


@weaver_test()
def test_a_reported_sync_failure_keeps_the_wait(monkeypatch):
    """Fabric reports a new shortcut as not found for minutes before it syncs."""

    resolver = _Resolver({"Sales.Order": NOT_FOUND}, {"Sales.Order": NOT_FOUND})
    endpoint = _Endpoint(("Sales", "Customer"))
    context = _context(endpoint, resolver)
    executor = EndpointObjectsExecutor()
    monkeypatch.setattr(endpoint_objects, "REFRESH_INTERVAL", 0.0)

    state = executor.execute(None, PAYLOAD, context).state
    state = _waits(executor, context, state)
    endpoint.listed.append(("Sales", "Order"))

    assert "visible_after_seconds" in executor.execute(None, None, context, state=state)
    assert len(resolver.refreshed) == 2


@weaver_test()
def test_a_timeout_names_each_table_with_the_reason_fabric_last_gave(monkeypatch):
    resolver = _Resolver({"sales.order": NOT_FOUND})
    context = _context(_Endpoint(), resolver)
    executor = EndpointObjectsExecutor()
    monkeypatch.setattr(endpoint_objects, "REFRESH_INTERVAL", 0.0)
    state = executor.execute(None, PAYLOAD, context).state
    monkeypatch.setattr(endpoint_objects, "TIMEOUT", 0.0)

    with pytest.raises(InstallError) as raised:
        executor.execute(None, None, context, state=state)

    message = str(raised.value)
    assert "  Input_Dev.Sales.Customer\n" in message
    assert "Input_Dev.Sales.Order: Fabric reported DeltaTableNotFound" in message
    assert message.endswith("Retry once Fabric has synced them.")


@weaver_test()
def test_the_wait_outlasts_its_own_limit_so_its_failure_names_the_tables():
    from weaver.mutation.executor import physical_driver

    driver = physical_driver(EndpointObjectsExecutor(), {}, required_capabilities=())

    assert driver.timeout > endpoint_objects.TIMEOUT
