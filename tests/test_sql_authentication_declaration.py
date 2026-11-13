"""Desktop and Fabric-session authentication remain explicit and separate."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from support.weaver_test import weaver_test

from weaver.errors import CommandError
from weaver.fabric.auth import SQL_SCOPE
from weaver.fabric.sql import (
    FABRIC_SQL_AUDIENCE,
    desktop_sql_pool,
    fabric_sql_pool,
)
from weaver.sql import SqlEndpoint
from weaver.targets import WarehouseTarget
from weaver.workspaces import Workspace


class Resolver:
    def sql_endpoint(self, target):
        return SqlEndpoint("server.example", target.warehouse.name)


@weaver_test()
def test_desktop_authentication_uses_the_injected_credential_and_sql_scope(monkeypatch):
    credential = object()
    calls = []

    def token(scope, supplied):
        calls.append((scope, supplied))
        return "desktop-token"

    monkeypatch.setattr("weaver.fabric.sql.get_token", token)
    pool = desktop_sql_pool(
        WarehouseTarget.parse("Reporting"),
        Workspace(workspace="Analytics"),
        resolver=Resolver(),
        credential=credential,
        connection_factory=lambda endpoint, authentication: (
            authentication.connection_arguments(),
            SimpleNamespace(close=lambda: None),
        )[1],
    )
    with pool.lease():
        pass

    assert calls == [(SQL_SCOPE, credential)]
    pool.close()


@weaver_test()
def test_sql_scopes_reuse_the_session_sql_token(monkeypatch):
    from weaver.sessions.console import ConsoleSession

    calls = []
    connections = []

    def acquire(scope):
        calls.append(scope)
        return SimpleNamespace(token="test-token", expires_on=1e12)

    def connect(endpoint, authentication):
        authentication.connection_arguments()
        connections.append(endpoint)
        return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr("weaver.sql.connection.connect", connect)
    credential = SimpleNamespace(get_token=acquire)
    with ConsoleSession(credential=credential) as session:
        for name in ("one", "two"):
            executor = session.sql_executor(
                SqlEndpoint("server.example", name), workspace=Workspace(workspace=name)
            )
            with executor.pool.lease():
                pass

    assert len(connections) == 2
    assert calls == [SQL_SCOPE]


@weaver_test()
def test_fabric_authentication_uses_notebookutils_not_the_desktop_chain(monkeypatch):
    from weaver.fabric.session import FabricSessionResolver

    calls = []
    credentials = SimpleNamespace(
        getToken=lambda audience: calls.append(audience) or "fabric-token"
    )
    resolver = object.__new__(FabricSessionResolver)
    resolver._credentials = credentials
    resolver.sql_endpoint = Resolver().sql_endpoint

    pool = fabric_sql_pool(
        WarehouseTarget.parse("Reporting"),
        Workspace(workspace="Analytics"),
        resolver=resolver,
        credentials=credentials,
        connection_factory=lambda endpoint, authentication: (
            authentication.connection_arguments(),
            SimpleNamespace(close=lambda: None),
        )[1],
    )
    with pool.lease():
        pass

    assert calls == [FABRIC_SQL_AUDIENCE]
    pool.close()


@weaver_test()
def test_fabric_authentication_fails_clearly_outside_fabric():
    with pytest.raises(CommandError, match="only inside"):
        fabric_sql_pool(
            WarehouseTarget.parse("Reporting"),
            Workspace(workspace="Analytics"),
        )
