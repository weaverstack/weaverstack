"""The Catalogue Dashboard exported as static pages, from a desktop and in Fabric.

A Dashboard over the suite's catalogue is deployed to a fixed name, found or
created, then exported by the desktop to a local folder and by a Session in
Fabric to OneLake, as a scheduled notebook would. What the export writes is
settled in ``tests/test_catalogue_dashboard_export_cycle.py``; a tenant
answers whether the page data reaches each position whole.
"""

from __future__ import annotations

import os

import pytest
from support.weaver_test import register_session, weaver_test

import weaver

DASHBOARD = os.environ.get("WEAVER_PYTEST_DASHBOARD", "PYTEST_DASHBOARD")
PAGES = {
    "workspaces",
    "overview",
    "health",
    "orchestration",
    "performance",
    "gantt",
    "entities",
    "semantic",
}


@pytest.fixture(scope="module")
def dashboard(fabric_workspace, fabric_catalogue, weaver_session):
    register_session(weaver_session)
    deployed = weaver.deploy_catalogue_dashboard(
        catalogue=f"{fabric_workspace.workspace}/Warehouse/{fabric_catalogue.name}",
        name=DASHBOARD,
        session=weaver_session,
    )
    assert deployed.succeeded, deployed.errors
    return DASHBOARD


@weaver_test(remote=True, resources={"rest"})
def test_a_desktop_exports_every_page_to_a_folder(dashboard, weaver_session, tmp_path):
    result = weaver.export_catalogue_dashboard(
        tmp_path / "dashboard", name=dashboard, session=weaver_session
    )

    assert {page.page for page in result.pages} == PAGES
    written = {path.name for path in (tmp_path / "dashboard").iterdir()}
    assert written == {f"{page}.html" for page in PAGES} | {"index.html"}
    for page in result.pages:
        html = (tmp_path / "dashboard" / page.file).read_text(encoding="utf-8")
        assert len(html) == page.characters
        assert 'id="wd-data"' in html and "page" in html


@weaver_test(hosted=True, resources={"onelake", "rest"})
def test_a_notebook_exports_every_page_to_onelake(
    dashboard, livy_session, fabric_workspace, fabric_target_lakehouse, weaver_session
):
    """Run in Fabric, as a scheduled notebook runs it, writing to a Lakehouse."""

    from weaver.targets import ItemRef

    # A notebook names OneLake as Spark does; the desktop reads it back over DFS.
    lakehouse = ItemRef(fabric_target_lakehouse.name)
    resolver = weaver_session.resolver(fabric_workspace)
    folder = f"{resolver.spark_root(lakehouse)}/Files/_dashboard_export"
    readable = resolver.files_root(lakehouse).join("_dashboard_export").value
    payload = livy_session.run(
        "import weaver\n"
        "result = weaver.export_catalogue_dashboard(\n"
        f"    {folder!r}, name={dashboard!r}, workspace={fabric_workspace.workspace!r}\n"
        ")\n"
        "emit(result.report())\n"
    ).payload

    assert {page["page"] for page in payload["pages"]} == PAGES
    assert payload["path"] == folder
    store = weaver_session.transport_store(fabric_workspace)
    from weaver.locations import Location

    index = store.read(Location(f"{readable}/index.html")).decode("utf-8")
    workspaces = next(p for p in payload["pages"] if p["page"] == "workspaces")
    assert len(index) == workspaces["characters"]
    assert '<a href="entities.html">' in index
