from support.weaver_test import weaver_test

from weaver.fabric.client import FabricClient
from weaver.fabric.resolution import FabricResolver
from weaver.fabric.resources import Item
from weaver.targets import ItemRef, WarehouseTarget
from weaver.workspaces import Workspace


class WarehouseClient(FabricClient):
    def __init__(self):
        self.calls = []

    def paged(self, path):
        self.calls.append(path)
        if path == "workspaces":
            return [{"id": "workspace-one", "displayName": "Sales"}]
        if path.endswith("/warehouses"):
            return [
                {
                    "id": name.lower(),
                    "displayName": name,
                    "type": "Warehouse",
                    "workspaceId": "workspace-one",
                    "properties": {
                        "connectionString": "example.datawarehouse.fabric.microsoft.com"
                    },
                }
                for name in ("Catalogue", "Mart")
            ]
        if path.endswith("/items?type=Warehouse"):
            return self.paged("workspaces/workspace-one/warehouses")
        raise AssertionError(path)

    def get_json(self, path):
        self.calls.append(path)
        return {"connectionString": "example.datawarehouse.fabric.microsoft.com"}


@weaver_test()
def test_warehouse_endpoints_share_one_typed_metadata_listing():
    client = WarehouseClient()
    resolver = FabricResolver(Workspace(workspace="Sales"), client=client)
    first = resolver.sql_endpoint(WarehouseTarget(ItemRef("Catalogue")))
    second = resolver.sql_endpoint(WarehouseTarget(ItemRef("Mart")))
    assert first.warehouse_id == "catalogue"
    assert second.warehouse_id == "mart"
    assert first.database == "Catalogue"
    assert second.database == "Mart"
    assert first.server == second.server == "example.datawarehouse.fabric.microsoft.com"
    assert client.calls == ["workspaces", "workspaces/workspace-one/warehouses"]


@weaver_test()
def test_listed_endpoint_never_replaces_a_previously_bound_warehouse_identity():
    client = WarehouseClient()
    resolver = FabricResolver(Workspace(workspace="Sales"), client=client)
    resolver._items["Catalogue:Warehouse"] = Item(
        "original", "Catalogue", "Warehouse", "workspace-one"
    )
    endpoint = resolver.sql_endpoint(WarehouseTarget(ItemRef("Catalogue")))
    assert endpoint.warehouse_id == "original"
    assert (
        client.calls[-1]
        == "workspaces/workspace-one/warehouses/original/connectionString"
    )


@weaver_test()
def test_absent_endpoint_properties_keep_the_existing_connection_string_lookup():
    class LegacyClient(WarehouseClient):
        def paged(self, path):
            rows = super().paged(path)
            return [
                {key: value for key, value in row.items() if key != "properties"}
                for row in rows
            ]

    client = LegacyClient()
    resolver = FabricResolver(Workspace(workspace="Sales"), client=client)
    endpoint = resolver.sql_endpoint(WarehouseTarget(ItemRef("Catalogue")))
    assert endpoint.warehouse_id == "catalogue"
    assert (
        client.calls[-1]
        == "workspaces/workspace-one/warehouses/catalogue/connectionString"
    )


@weaver_test()
def test_a_shared_directory_lists_again_for_a_workspace_created_after_it():
    from weaver.fabric.resources import WorkspaceDirectory

    class Directory(FabricClient):
        def __init__(self):
            self.workspaces = [{"id": "sales", "displayName": "Sales"}]
            self.listings = 0

        def paged(self, path):
            assert path == "workspaces"
            self.listings += 1
            return list(self.workspaces)

    client, directory = Directory(), WorkspaceDirectory()
    first = FabricResolver(
        Workspace(workspace="Sales"), client=client, directory=directory
    )
    assert first.workspace.id == "sales"
    client.workspaces.append({"id": "inventory", "displayName": "Inventory"})
    second = FabricResolver(
        Workspace(workspace="Inventory"), client=client, directory=directory
    )
    third = FabricResolver(
        Workspace(workspace="Sales"), client=client, directory=directory
    )
    assert second.workspace.id == "inventory"
    assert third.workspace.id == "sales"
    assert client.listings == 2
