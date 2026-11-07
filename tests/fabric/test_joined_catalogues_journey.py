"""Two teams' catalogues, joined where one shortcuts the other's table.

The hub team owns a Warehouse in the suite's workspace and its own catalogue.
The spoke team, in its own workspace with its own catalogue, shortcuts the hub's
``HUB.Customer`` into a Bridge Lakehouse and counts it into a Mart Warehouse.
Each team builds alone. Then:

.. code-block:: text

    joined load     both teams in one graph: the hub load, its OneLake
                    publication, the Bridge endpoint refresh, then the Mart
    failure         the hub's source is dropped and the hub's load fails
    health          the spoke, reading the hub for context, sees its Mart
                    behind a failed load in the hub
    repair          the hub's source returns with more rows; one joined --stale
                    load runs only what the failure reached, barriers included
    spoke recovery  the hub reloads alone; the spoke's --stale load syncs its
                    own Bridge endpoint and runs only its stale Mart, which reads
                    what the hub published, recorded in its own catalogue
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from support.weaver_test import weaver_test

import weaver
from weaver.errors import WeaverError

SOURCE = "CustomerSource"


def _write(root: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def hub_project(root: Path, estate, environment: str) -> Path:
    names = estate.names
    return _write(
        root,
        {
            "workspace-config.yml": (
                f"workspace: {estate.hub_workspace}\n"
                f"environment: {environment}\n"
                f"catalogue: Warehouse/{names['hub_weaver']}\n\n"
                "targets:\n"
                f"  Warehouse/Hub: {names['hub_warehouse']}\n"
            ),
            "Warehouse/Hub/schemas/HUB.yml": (
                "Schema ID: HUB\n\nDescription: |\n  The hub team's tables.\n"
            ),
            "Warehouse/Hub/HUB.Customer.sql": (
                "/*\nTable ID: HUB.Customer\n\nDescription: Every customer.\n\n"
                "Lineage: The customer source the test controls.\n\n"
                "Primary key: CustomerId\n*/\n"
                "select CustomerId, CustomerName\n"
                f"from [{names['hub_warehouse']}].[dbo].[{SOURCE}]\n"
            ),
        },
    )


def spoke_project(root: Path, estate, environment: str) -> Path:
    names = estate.names
    return _write(
        root,
        {
            "workspace-config.yml": (
                f"workspace: {estate.spoke_workspace}\n"
                f"environment: {estate.hub_workspace}/{environment}\n"
                f"catalogue: Warehouse/{names['spoke_weaver']}\n\n"
                "targets:\n"
                f"  Lakehouse/Bridge: {names['spoke_lakehouse']}\n"
                f"  Warehouse/Mart: {names['spoke_warehouse']}\n"
            ),
            "Lakehouse/Bridge/schemas/HUB.yml": (
                "Schema ID: HUB\n\nDescription: |\n  The hub's tables, shortcut.\n"
            ),
            "Lakehouse/Bridge/shortcuts.py": (
                "from weaver import Shortcut\n\n"
                "HUB__Customer = Shortcut(\n"
                '    shortcut_type="table",\n'
                '    target_type="physical",\n'
                f'    target="Warehouse/{names["hub_warehouse"]}/Tables/HUB.Customer",\n'
                f'    workspace="{estate.hub_workspace}",\n'
                ")\n"
            ),
            "Warehouse/Mart/shortcuts.yml": (
                "logical:\n"
                "  Warehouse/Mart/HUB.Customer: Lakehouse/Bridge/Tables/HUB.Customer\n"
            ),
            "Warehouse/Mart/schemas/HUB.yml": (
                "Schema ID: HUB\n\nDescription: |\n  The hub's tables, read "
                "through the Bridge.\n"
            ),
            "Warehouse/Mart/schemas/MART.yml": (
                "Schema ID: MART\n\nDescription: |\n  The spoke team's tables.\n"
            ),
            "Warehouse/Mart/MART.Summary.sql": (
                "/*\nTable ID: MART.Summary\n\nDescription: How many customers "
                "there are.\n\nLineage: HUB.Customer.\n\nPrimary key: Customers\n*/\n"
                "select count(*) as Customers\nfrom [HUB].[Customer]\n"
            ),
        },
    )


@dataclass
class Estate:
    session: object
    hub: Path
    spoke: Path
    joined: object

    @property
    def hub_config(self) -> str:
        return str(self.hub / "workspace-config.yml")

    @property
    def spoke_config(self) -> str:
        return str(self.spoke / "workspace-config.yml")

    @property
    def catalogues(self) -> list[str]:
        names = self.joined.names
        return [
            f"{self.joined.hub_workspace}/Warehouse/{names['hub_weaver']}",
            f"{self.joined.spoke_workspace}/Warehouse/{names['spoke_weaver']}",
        ]

    def _warehouse(self, workspace: str, role: str):
        from weaver.targets import WarehouseTarget
        from weaver.workspaces import Workspace

        return (
            WarehouseTarget.parse(self.joined.names[role]),
            Workspace(workspace=workspace),
        )

    def seed(self, customers: int | None) -> None:
        """Replace the hub's source with ``customers`` rows, or drop it."""

        target, workspace = self._warehouse(self.joined.hub_workspace, "hub_warehouse")
        script = f"drop table if exists [dbo].[{SOURCE}];\n"
        if customers is not None:
            rows = ", ".join(f"({n}, 'Customer {n}')" for n in range(1, customers + 1))
            script += (
                f"create table [dbo].[{SOURCE}] "
                "(CustomerId int not null, CustomerName varchar(64));\n"
                f"insert into [dbo].[{SOURCE}] values {rows};\n"
            )
        self.session.execute_tsql(script, target=target, workspace=workspace)

    def await_published(self, timeout: float = 300.0) -> None:
        """Wait until OneLake holds the hub table a shortcut is created onto.

        A rebuilt Warehouse table reaches OneLake after its transaction, and the
        spoke's build checks its shortcut's source exists.
        """

        import time

        from weaver.declaration.metadata import ObjectId
        from weaver.run.publication import published_commits

        _target, workspace = self._warehouse(self.joined.hub_workspace, "hub_warehouse")
        name = self.joined.names["hub_warehouse"]
        deadline = time.monotonic() + timeout
        while not published_commits(
            name, ObjectId("HUB", "Customer"), self.session, workspace
        ):
            assert time.monotonic() < deadline, "the hub table never reached OneLake"
            time.sleep(10)

    def customers(self) -> int:
        target, workspace = self._warehouse(
            self.joined.spoke_workspace, "spoke_warehouse"
        )
        (row,) = self.session.query_tsql(
            "select Customers from [MART].[Summary]", target=target, workspace=workspace
        )
        return int(row["Customers"])

    def statuses(self) -> dict:
        """Each catalogue's load state, by ``Schema.Object``."""

        from weaver.targets import WarehouseTarget
        from weaver.workspaces import Workspace

        found = {}
        names = self.joined.names
        for workspace, catalogue in (
            (self.joined.hub_workspace, names["hub_weaver"]),
            (self.joined.spoke_workspace, names["spoke_weaver"]),
        ):
            rows = self.session.query_tsql(
                "select [Schema name] as schema_name, [Object name] as object_name, "
                "[Result] as result, [Workflow ID] as workflow_id "
                "from [_].[LoadStatus]",
                target=WarehouseTarget.parse(catalogue),
                workspace=Workspace(workspace=workspace),
            )
            found[workspace] = {
                f"{row['schema_name']}.{row['object_name']}": (
                    str(row["result"]).casefold(),
                    row["workflow_id"],
                )
                for row in rows
            }
        return found


def _clean(estate: Estate) -> None:
    """Empty both teams' items and catalogues, as a first build expects."""

    for config in (estate.spoke_config, estate.hub_config):
        try:
            weaver.wipe(
                workspace_config=config,
                catalogue_action="remove",
                session=estate.session,
            )
        except WeaverError as exc:
            print(f"nothing to wipe for {config}: {exc}")


@pytest.fixture(scope="module")
def journey(tmp_path_factory, weaver_session, joined_estate, environment_name):
    """Every step, each observed as it finished."""

    root = tmp_path_factory.mktemp("joined")
    estate = Estate(
        session=weaver_session,
        hub=hub_project(root / "hub", joined_estate, environment_name),
        spoke=spoke_project(root / "spoke", joined_estate, environment_name),
        joined=joined_estate,
    )
    hub, spoke = joined_estate.hub_workspace, joined_estate.spoke_workspace
    _clean(estate)
    estate.seed(3)
    steps = {}

    built = weaver.build(
        str(estate.hub), workspace_config=estate.hub_config, session=weaver_session
    )
    assert built.succeeded, built
    estate.await_published()
    built = weaver.build(
        str(estate.spoke), workspace_config=estate.spoke_config, session=weaver_session
    )
    assert built.succeeded, built

    first = weaver.load(
        [hub, spoke],
        catalogue=estate.catalogues,
        workspace_config=estate.spoke_config,
        session=weaver_session,
    )
    steps["first"] = (first, estate.customers(), estate.statuses())

    estate.seed(None)
    failed = weaver.load(
        workspace_config=estate.hub_config,
        fault_tolerant=True,
        session=weaver_session,
    )
    health = weaver.health(
        [spoke],
        catalogue=estate.catalogues,
        workspace_config=estate.spoke_config,
        session=weaver_session,
    )
    steps["failure"] = (failed, health)

    estate.seed(5)
    repaired = weaver.load(
        [hub, spoke],
        catalogue=estate.catalogues,
        stale=True,
        workspace_config=estate.spoke_config,
        session=weaver_session,
    )
    steps["repair"] = (repaired, estate.customers(), estate.statuses())

    estate.seed(6)
    weaver.load(workspace_config=estate.hub_config, session=weaver_session)
    behind = weaver.health(
        [spoke],
        catalogue=estate.catalogues,
        workspace_config=estate.spoke_config,
        session=weaver_session,
    )
    recovered = weaver.load(
        [spoke],
        catalogue=estate.catalogues,
        stale=True,
        workspace_config=estate.spoke_config,
        session=weaver_session,
    )
    steps["recovery"] = (behind, recovered, estate.statuses(), estate.customers())
    return steps


def _loads(report) -> dict:
    return {
        (node.catalogue, node.logical_id): node.status
        for node in report.nodes
        if node.logical_id
    }


def _barriers(report) -> list:
    return sorted(
        (node.catalogue, node.primitive_kind, node.status)
        for node in report.nodes
        if not node.logical_id
    )


@weaver_test(integration=True)
def test_one_load_runs_both_teams_through_publication_and_the_endpoint(
    journey, joined_estate
):
    report, customers, statuses = journey["first"]
    hub, spoke = joined_estate.hub_workspace, joined_estate.spoke_workspace

    assert report.succeeded, report
    assert _loads(report) == {
        (hub, "Warehouse/Hub/HUB.Customer"): "succeeded",
        (spoke, "Warehouse/Mart/MART.Summary"): "succeeded",
    }
    assert _barriers(report) == [
        (hub, "onelake_publication", "succeeded"),
        (spoke, "endpoint_refresh", "succeeded"),
    ]
    order = [node.node_id for node in report.nodes]
    assert order.index(
        f"{hub}::load:Warehouse/{joined_estate.names['hub_warehouse']}/HUB.Customer"
    ) < order.index(
        f"{spoke}::load:Warehouse/{joined_estate.names['spoke_warehouse']}/MART.Summary"
    )
    assert customers == 3
    assert statuses[hub]["HUB.Customer"] == ("succeeded", report.workflow_id)
    assert statuses[spoke]["MART.Summary"] == ("succeeded", report.workflow_id)


@weaver_test(integration=True)
def test_the_spoke_sees_its_mart_behind_a_failed_load_in_the_hub(
    journey, joined_estate
):
    failed, health = journey["failure"]
    hub, spoke = joined_estate.hub_workspace, joined_estate.spoke_workspace

    assert _loads(failed) == {(None, "Warehouse/Hub/HUB.Customer"): "failed"}
    # Naming the spoke's items reports the spoke; the hub gives context.
    assert [each.label for each in health.catalogues] == [spoke]
    spoke_report = next(
        each.report for each in health.catalogues if each.label == spoke
    )
    (finding,) = [
        each
        for each in spoke_report.findings
        if each.object_id == "Warehouse/Mart/MART.Summary"
        and each.code == "load_ancestor_unestablished"
    ]
    assert finding.message == (
        f"the last load of {hub}: Warehouse/Hub/HUB.Customer failed"
    )
    assert "impact" not in health.to_mapping()


@weaver_test(integration=True)
def test_a_joined_stale_load_repairs_only_what_the_failure_reached(
    journey, joined_estate
):
    report, customers, statuses = journey["repair"]
    hub, spoke = joined_estate.hub_workspace, joined_estate.spoke_workspace

    assert report.succeeded, report
    assert _loads(report) == {
        (hub, "Warehouse/Hub/HUB.Customer"): "succeeded",
        (spoke, "Warehouse/Mart/MART.Summary"): "succeeded",
    }
    assert [kind for _, kind, _ in _barriers(report)] == [
        "onelake_publication",
        "endpoint_refresh",
    ]
    assert customers == 5
    assert statuses[hub]["HUB.Customer"][1] == statuses[spoke]["MART.Summary"][1]


@weaver_test(integration=True)
def test_the_spoke_recovers_its_own_stale_objects_and_nothing_else(
    journey, joined_estate
):
    behind, recovered, statuses, customers = journey["recovery"]
    spoke = joined_estate.spoke_workspace

    spoke_report = next(
        each.report for each in behind.catalogues if each.label == spoke
    )
    assert "load_stale_ancestor" in {
        each.code
        for each in spoke_report.findings
        if each.object_id == "Warehouse/Mart/MART.Summary"
    }
    assert recovered.succeeded, recovered
    assert _loads(recovered) == {(spoke, "Warehouse/Mart/MART.Summary"): "succeeded"}
    # The hub's load is not part of this run, so the run waits for its last
    # commit to be published, then syncs the spoke's own Bridge endpoint.
    assert _barriers(recovered) == [
        (joined_estate.hub_workspace, "onelake_publication", "succeeded"),
        (spoke, "endpoint_refresh", "succeeded"),
    ]
    assert customers == 6
    assert statuses[spoke]["MART.Summary"] == ("succeeded", recovered.workflow_id)
