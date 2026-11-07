"""Source metadata uses each host's Session-owned TDS and REST capabilities."""

from types import SimpleNamespace

import pytest
from support.weaver_test import weaver_test
from support.workspaces import _identifier
from test_semantic_source_build_cycle import SourceInventory
from test_sql_execution_boundary import Connection, Cursor

from weaver.fabric.resolution import FabricResolver
from weaver.fabric.session import FabricSessionResolver
from weaver.sessions.console import ConsoleSession
from weaver.sessions.notebook import NotebookSession
from weaver.store import FilesystemStore
from weaver.workspaces import Workspace


class EndpointInventory(SourceInventory):
    def get_json(self, path, **kwargs):
        if "/lakehouses/" in path:
            self.requested.append(path)
            return {
                "properties": {
                    "sqlEndpointProperties": {
                        "id": _identifier("SQLEndpoint", "Serving_Dev"),
                        "connectionString": "lake.datawarehouse.fabric.microsoft.com",
                    }
                }
            }
        return super().get_json(path, **kwargs)


@weaver_test()
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("item_type", ["Warehouse", "Lakehouse"])
def test_source_shape_and_endpoint_use_selected_session_identity(
    monkeypatch, native, item_type
):
    from weaver.sql import connection

    workspace = Workspace(workspace="Demo")
    inventory = EndpointInventory(
        "Demo", [("Warehouse", "Serving_Dev"), ("Lakehouse", "Serving_Dev")]
    )
    columns = [("Id", "bigint"), ("Label", "varchar")]
    cursor = Cursor(rows=columns, columns=["column_name", "data_type"])
    connections = []
    audiences = []

    def connect(endpoint, authentication):
        authentication.connection_arguments()
        connections.append(endpoint)
        return Connection(cursor)

    monkeypatch.setattr(connection, "connect", connect)
    if native:
        credentials = SimpleNamespace(
            getToken=lambda audience: audiences.append(audience) or "test-token"
        )
        resolver = FabricSessionResolver(
            workspace,
            runtime=SimpleNamespace(
                context={
                    "currentWorkspaceName": "Demo",
                    "currentWorkspaceId": _identifier("workspace", "Demo"),
                }
            ),
            lakehouse=SimpleNamespace(
                get=lambda *a, **k: {
                    "id": _identifier("Lakehouse", "Serving_Dev"),
                    "displayName": "Serving_Dev",
                }
            ),
            credentials=credentials,
            client=inventory,
        )
        session = NotebookSession(
            workspace=workspace, resolver=resolver, store=FilesystemStore()
        )
    else:
        credential = SimpleNamespace(
            get_token=lambda audience: (
                audiences.append(audience)
                or SimpleNamespace(token="test-token", expires_on=1)
            )
        )
        session = ConsoleSession(
            workspace=workspace,
            resolver=FabricResolver(workspace, client=inventory),
            credential=credential,
            store=FilesystemStore(),
            progress=False,
        )
    with session:
        observed = session.semantic_source(
            "Serving_Dev", item_type=item_type, schema="Cake", name="Sales"
        )
        assert observed["item_type"] == item_type
        assert observed["item_id"] == _identifier(item_type, "Serving_Dev")
        # Connections are created by database name; item_id carries identity.
        assert observed["database"] == "Serving_Dev"
        assert observed["source_columns"] == [
            {"column_name": name, "data_type": kind} for name, kind in columns
        ]
        assert len(connections) == 1
        # TDS addresses the endpoint by ID; the model's M names the database.
        assert connections[0].database == (
            _identifier("SQLEndpoint", "Serving_Dev")
            if item_type == "Lakehouse"
            else "Serving_Dev"
        )
        assert "TABLE_SCHEMA = N'Cake'" in cursor.calls[0][0]
        if native:
            assert session.scope()._spark is None
            assert audiences == ["https://database.windows.net/"]
        else:
            assert not session.scope().livy.acquired
            assert audiences == ["https://database.windows.net/.default"]


@weaver_test()
def test_a_lakehouse_table_the_endpoint_has_not_listed_is_refreshed_then_read():
    """A new shortcut table appears in the endpoint only once it is synced."""

    from weaver.sessions.semantic_sources import semantic_source

    refreshed = []
    answers = [[], [{"column_name": "Id", "data_type": "bigint"}]]
    lakehouse = SimpleNamespace(
        name="Bridge", type="Lakehouse", id="lakehouse-id", workspace_id="ws-id"
    )
    resolver = SimpleNamespace(
        client=SimpleNamespace(
            get_json=lambda path: {
                "properties": {
                    "sqlEndpointProperties": {
                        "id": "endpoint-id",
                        "connectionString": "lake.datawarehouse.fabric.microsoft.com",
                    }
                }
            }
        ),
        refresh_sql_endpoint=lambda item, tables: refreshed.append((str(item), tables)),
    )
    session = SimpleNamespace(
        resolve_item=lambda *a, **k: lakehouse,
        resolver=lambda workspace: resolver,
        query_tsql=lambda *a, **k: answers.pop(0),
    )

    observed = semantic_source(
        session,
        "Bridge",
        item_type="Lakehouse",
        schema="GOLD",
        name="CustomerSales",
        include_columns=True,
        workspace=None,
    )

    assert refreshed == [("Bridge", [("GOLD", "CustomerSales")])]
    assert observed["source_columns"] == [{"column_name": "Id", "data_type": "bigint"}]
