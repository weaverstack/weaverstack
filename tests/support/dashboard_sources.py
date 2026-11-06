"""Catalogues a Catalogue Dashboard reads, described as its deployment finds them."""

from __future__ import annotations

from weaver.dashboard_model import RELATIONS, DashboardSource, declared_columns


def dashboard_source(
    workspace: str = "Demo",
    warehouse: str = "Catalogue",
    *,
    label: str | None = None,
    index: int = 1,
) -> DashboardSource:
    """A catalogue of this Weaver version, holding every table it declares."""

    return DashboardSource(
        label=label or workspace,
        reference=f"{workspace}/Warehouse/{warehouse}",
        workspace=workspace,
        workspace_id=f"{index:08d}-0000-4000-8000-000000000000",
        warehouse=warehouse,
        item_id=f"{index:08d}-1111-4000-8000-000000000000",
        server=f"{workspace.lower()}.datawarehouse.fabric.microsoft.com",
        columns={table: declared_columns(table) for table in RELATIONS.values()},
    )


def dashboard_sources(count: int = 2) -> tuple[DashboardSource, ...]:
    return tuple(dashboard_source(f"Team{i}", index=i) for i in range(1, count + 1))
