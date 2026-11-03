"""One workflow loads, then tests only what is stale, from a desktop and in Fabric.

The generated Warehouse example reaches TDS and REST and starts no Spark from
the desktop. The in-Fabric half runs the same workflow in a notebook Session
over the estate the desktop half built.
"""

from __future__ import annotations

import json

from support.weaver_test import register_session, weaver_test

import weaver
from weaver.config import load_workspace
from weaver.health import GREEN
from weaver.sessions.program import FabricProgram
from weaver.sessions.run_in_fabric import _workspace_literal
from weaver.targets import ItemRef, WarehouseTarget


def _ran(report) -> set[str]:
    return {node.logical_id for node in report.nodes}


def _recorded(session, catalogue: str, item: str) -> dict[str, str]:
    """Each validation of ``item`` and the workflow its current result came from."""

    rows = session.query_tsql(
        "SELECT [Schema name] AS s, [Object name] AS o, [Workflow ID] AS w "
        "FROM [_].[TestStatus] WHERE [Item type] = 'Warehouse' AND [Item name] = ?",
        target=WarehouseTarget(ItemRef(catalogue)),
        parameters=[item],
    )
    return {f"Warehouse/{item}/{row['s']}.{row['o']}": row["w"] for row in rows}


def _hosted_program(configured, items) -> str:
    return (
        "import weaver\n"
        "from weaver.sessions import NotebookSession\n"
        "from weaver.workspaces import *\n"
        f"workspace = {_workspace_literal(configured)}\n"
        f"items = {json.dumps(items)}\n"
        "with NotebookSession(workspace=workspace, spark=spark) as session:\n"
        "    with weaver.workflow(session=session) as flow:\n"
        "        loaded = weaver.load(items)\n"
        "        tested = weaver.test(items, stale=True)\n"
        "emit({'workflow_id': flow.workflow_id, 'loaded': loaded.to_mapping(),\n"
        "      'tested': tested.to_mapping()})\n"
    )


@weaver_test(integration=True, resources={"rest", "tds", "livy"})
def test_a_workflow_tests_what_its_load_made_stale_in_both_positions(
    fabric_workspace,
    fabric_catalogue,
    environment_name,
    emptied_disposable_warehouse,
    weaver_session,
    tmp_path,
):
    session = register_session(weaver_session)
    warehouse = emptied_disposable_warehouse.item.name
    weaver.initialise(
        tmp_path,
        workspace=fabric_workspace.workspace,
        catalogue=fabric_catalogue.name,
        environment=environment_name,
        warehouse=warehouse,
        example="Sales",
        session=session,
    )
    configuration = tmp_path / "workspace-config.yml"
    items = [f"Warehouse/{warehouse}"]
    built = weaver.build(
        tmp_path, items=items, workspace_config=configuration, session=session
    )
    assert built.succeeded

    # Desktop: everything is new, so everything runs once and then nothing.
    with weaver.workflow(session=session, workspace_config=configuration) as first:
        loaded = weaver.load(items)
        fresh = weaver.test(items, stale=True)
        settled = weaver.test(items, stale=True)
    assert loaded.succeeded and fresh.succeeded and settled.succeeded
    assert fresh.nodes and settled.nodes == ()
    assert loaded.workflow_id == fresh.workflow_id == first.workflow_id

    # Desktop again: a second load puts behind exactly what Health says it does.
    with weaver.workflow(session=session, workspace_config=configuration) as second:
        reloaded = weaver.load(items)
        health = weaver.health(items)
        behind = weaver.test(items, stale=True)
    not_green = {finding.object_id for finding in health.tests.findings}
    assert health.tests.status != GREEN
    assert _ran(behind) == not_green
    assert not_green <= _ran(fresh)
    assert reloaded.workflow_id == behind.workflow_id == second.workflow_id
    assert first.workflow_id != second.workflow_id

    recorded = _recorded(session, fabric_catalogue.name, warehouse)
    assert {recorded[name] for name in _ran(behind)} == {second.workflow_id}
    assert {recorded[name] for name in _ran(fresh) - _ran(behind)} <= {
        first.workflow_id
    }

    # In Fabric: the same workflow in a notebook Session.
    def remote_only():
        raise AssertionError("this workflow must run in Fabric")

    configured = load_workspace(configuration)
    carried = session.execute_python(
        FabricProgram(
            name="workflow_stale_test",
            call=remote_only,
            source=_hosted_program(configured, items),
        ),
        workspace=fabric_workspace,
    )
    hosted = carried["workflow_id"]
    assert (
        carried["loaded"]["workflow_id"] == carried["tested"]["workflow_id"] == hosted
    )
    hosted_ran = {node["logical_id"] for node in carried["tested"]["nodes"]}
    assert hosted_ran == not_green
    assert carried["tested"]["status"] == "passed"

    recorded = _recorded(session, fabric_catalogue.name, warehouse)
    assert {recorded[name] for name in hosted_ran} == {hosted}
