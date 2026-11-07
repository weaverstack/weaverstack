"""One Lakehouse item mirrored from a catalogue in another workspace.

The source item and its catalogue are in the suite's workspace. The mirror's
catalogue and Lakehouse are in the spoke workspace, the Lakehouse under the
source's name, as a development workspace's is. Build and load the source,
mirror the item across, report health, run its validations, then change one
declaration and build it into the mirror.

A tenant answers what only Fabric can: whether a shortcut, a persistent Spark
view and a shallow clone reach another workspace, and whether the catalogue's
rows arrive when no Warehouse can name the source. What the mirror decides is
settled in ``tests/test_mirror_plan_boundary.py`` and
``tests/test_mirror_boundary.py``.

Steps run in file order and do not cascade.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from support.acceptance import Acceptance
from support.build_envs import LAKEHOUSE_JOURNEY_FIXTURE
from support.weaver_test import register_session, weaver_test
from test_lakehouse_mirror_journey import MATERIALISED, POINTED_AT, WRAPPED, _change

import weaver
from weaver.catalogue.tables import CATALOGUE_SCHEMA
from weaver.catalogue.tables import MIRROR as MIRROR_TABLE
from weaver.targets import ItemRef, WarehouseTarget
from weaver.workspaces import Workspace

ITEM = "Lakehouse/Sales"


@dataclass(frozen=True)
class Estate:
    """What the estate holds at one moment, read after one transition."""

    #: ``path/name`` to the workspace ID each shortcut in the mirror reads from.
    shortcuts: dict[str, str] | None = None
    #: Relation names Spark reports in the mirror's ``DWG`` schema.
    relations: frozenset[str] | None = None
    #: ``Schema.Object`` to its source workspace, for live ``_.Mirror`` rows.
    borrowed: dict[str, str] | None = None
    #: ``Schema.Object`` to its source workspace, for rows marked deleted.
    retired: dict[str, str] | None = None
    #: Registry rows in the source catalogue and in the mirror's.
    registry: tuple[int, int] | None = None
    #: Rows the source table holds.
    source_rows: int | None = None
    #: ``Type/Name`` to the workspace each installation in the mirror names.
    installed: dict[str, str] | None = None


@pytest.fixture(scope="module")
def journey(
    fabric_workspace,
    fabric_workspace_item,
    fabric_catalogue,
    fabric_target_lakehouse,
    fabric_initialise_catalogue,
    cross_workspace_mirror,
    weaver_session,
    tmp_path_factory,
):
    """One estate: built, loaded, mirrored across workspaces, validated, changed."""

    register_session(weaver_session)
    fabric_initialise_catalogue()
    estate = LAKEHOUSE_JOURNEY_FIXTURE.disposable(tmp_path_factory.mktemp("xws-mirror"))

    run = Acceptance(name="cross-workspace-mirror")
    run.session = weaver_session
    run.workspace = fabric_workspace
    run.source_workspace_id = fabric_workspace_item.id
    run.source_name = fabric_target_lakehouse.name
    run.source_catalogue_name = fabric_catalogue.name
    run.spoke = Workspace(workspace=cross_workspace_mirror.workspace)
    run.target_name = cross_workspace_mirror.lakehouse
    run.catalogue_name = cross_workspace_mirror.catalogue
    run.config = _spoke_config(run, tmp_path_factory.mktemp("xws-config"))

    run.step(
        "build the source",
        lambda: weaver.build(
            str(estate.path),
            items=[f"{ITEM}=Lakehouse/{run.source_name}"],
            session=weaver_session,
        ),
    )
    run.step("load the source", lambda: weaver.load([ITEM], session=weaver_session))
    run.step(
        "mirror",
        lambda: weaver.mirror(session=weaver_session, workspace_config=run.config),
        observe=lambda: _observe(run),
    )
    run.step(
        "report health over the mirror",
        lambda: weaver.health(
            [ITEM], session=weaver_session, workspace_config=run.config
        ),
    )
    run.step(
        "validate the mirror",
        lambda: weaver.test(
            [ITEM], session=weaver_session, workspace_config=run.config
        ),
    )
    run.step("change one declaration", lambda: _change(estate))
    run.step(
        "build the changed declaration",
        lambda: weaver.build(
            str(estate.path),
            items=[ITEM],
            session=weaver_session,
            workspace_config=run.config,
        ),
        observe=lambda: _observe(run),
    )
    yield run
    run.close()


def _spoke_config(run, directory):
    """The spoke's configuration: its catalogue, the source it mirrors, its target."""

    environment = run.workspace.environment
    path = directory / "workspace-config.yml"
    path.write_text(
        "\n".join(
            (
                f"workspace: {run.spoke.workspace}",
                f"environment: {run.workspace.workspace}/{environment.name}",
                f"catalogue: Warehouse/{run.catalogue_name}",
                f"mirror: {run.workspace.workspace}/Warehouse/"
                f"{run.source_catalogue_name}",
                "",
                "targets:",
                f"  {ITEM}: {run.target_name}",
            )
        ),
        encoding="utf-8",
    )
    return path


def _spark(run, statement: str):
    return run.session.execute_spark_sql(
        statement, exact_case=True, workspace=run.spoke
    )


def _observe(run) -> Estate:
    """One reading of both workspaces after a transition."""

    resolver = run.session.resolver(run.spoke)
    shortcuts = {
        each.qualified: each.target_workspace_id or ""
        for each in resolver.onelake_shortcuts(ItemRef(run.target_name))
    }
    destination = resolver.spark_destination(ItemRef(run.target_name))
    relations = frozenset(
        str(row["tableName"])
        for row in _spark(run, f"SHOW TABLES IN {destination.qualified_schema('DWG')}")
    )
    mirror_sql = run.session.sql_executor(
        WarehouseTarget(ItemRef(run.catalogue_name)), workspace=run.spoke
    )
    rows, counted, installations = mirror_sql.query_result_sets(
        "select [Schema name], [Object name], [Source workspace name], "
        "year([Row delete datetime]) as [Deleted year] "
        f"from [{CATALOGUE_SCHEMA}].[{MIRROR_TABLE.name}] "
        "where [Item type] = N'Lakehouse';\n"
        f"select count(*) as [Rows] from [{CATALOGUE_SCHEMA}].[Registry];\n"
        "select [Item type], [Item name], [Workspace name] "
        f"from [{CATALOGUE_SCHEMA}].[Installation];"
    )
    (source,) = run.session.sql_executor(
        WarehouseTarget(ItemRef(run.source_catalogue_name)), workspace=run.workspace
    ).query(
        f"select count(*) as [Rows] from [{CATALOGUE_SCHEMA}].[Registry] "
        "where not ([Item type] = N'Warehouse' and [Item name] = N'_weaver')"
    )
    source_table = run.session.resolver(run.workspace).spark_destination(
        ItemRef(run.source_name)
    )
    (counted_rows,) = run.session.execute_spark_sql(
        f"SELECT count(*) as n FROM {source_table.qualify('DWG', 'Customer')}",
        exact_case=True,
        workspace=run.workspace,
    )

    def named(row):
        return f"{row['Schema name']}.{row['Object name']}"

    return Estate(
        shortcuts=shortcuts,
        relations=relations,
        borrowed={
            named(row): str(row["Source workspace name"])
            for row in rows
            if int(row["Deleted year"]) == 9999
        },
        retired={
            named(row): str(row["Source workspace name"])
            for row in rows
            if int(row["Deleted year"]) != 9999
        },
        registry=(int(source["Rows"]), int(counted[0]["Rows"])),
        source_rows=int(counted_rows["n"]),
        installed={
            f"{row['Item type']}/{row['Item name']}": str(row["Workspace name"])
            for row in installations
        },
    )


# --- what the mirror stood up -------------------------------------------------


@weaver_test(remote=True)
def test_every_table_and_folder_is_a_shortcut_into_the_source_workspace(journey):
    journey.require("mirror")
    held = journey["mirror"].observation.shortcuts

    for qualified in POINTED_AT:
        assert held.get(qualified) == journey.source_workspace_id, qualified


@weaver_test(remote=True)
def test_the_catalogue_records_the_workspace_each_object_is_borrowed_from(journey):
    journey.require("mirror")
    borrowed = journey["mirror"].observation.borrowed

    assert "Tables/DWG.Customer" in borrowed
    assert set(borrowed.values()) == {journey.workspace.workspace}


@weaver_test(remote=True)
def test_the_catalogue_crosses_the_workspaces_whole(journey):
    """No Warehouse names the source, so its rows arrive as literals."""

    journey.require("mirror")
    source, mirrored = journey["mirror"].observation.registry

    assert source > 0
    # The destination adds its own ``_weaver`` rows, built where it is.
    assert mirrored >= source


@weaver_test(remote=True)
def test_the_mirror_claims_only_items_in_its_own_workspace(journey):
    """An item the run left in the source's workspace is not the mirror's."""

    journey.require("mirror")
    installed = journey["mirror"].observation.installed

    assert installed[ITEM] == journey.spoke.workspace
    assert set(installed.values()) == {journey.spoke.workspace}


@weaver_test(remote=True, resources={"livy"})
def test_a_borrowed_table_reads_the_sources_rows_across_workspaces(journey):
    journey.require("mirror")
    resolver = journey.session.resolver(journey.spoke)
    destination = resolver.spark_destination(ItemRef(journey.target_name))

    seen = _spark(
        journey, f"SELECT count(*) as n FROM {destination.qualify('DWG', 'Customer')}"
    )

    assert int(seen[0]["n"]) == journey["mirror"].observation.source_rows > 0


@weaver_test(remote=True, resources={"livy"})
def test_a_wrapper_view_reads_the_sources_view_across_workspaces(journey):
    journey.require("mirror")
    resolver = journey.session.resolver(journey.spoke)
    destination = resolver.spark_destination(ItemRef(journey.target_name))

    for qualified in WRAPPED:
        schema, _, name = qualified.partition(".")
        assert _spark(journey, f"SELECT * FROM {destination.qualify(schema, name)}")


@weaver_test(remote=True)
def test_health_reads_the_source_catalogue_in_its_own_workspace(journey):
    journey.require("report health over the mirror")
    report = journey["report health over the mirror"].result

    assert [
        (finding.code, finding.object_id) for finding in report.build.findings
    ] == []
    assert report.load.subjects > 0


@weaver_test(remote=True)
def test_the_mirror_runs_its_installed_validations(journey):
    journey.require("validate the mirror")
    report = journey["validate the mirror"].result

    assert report.nodes, "dispatch reached no validation"
    assert {node.status for node in report.nodes} == {"passed"}


# --- one changed declaration --------------------------------------------------


@weaver_test(remote=True)
def test_the_changed_object_is_materialised_from_the_other_workspace(journey):
    journey.require("build the changed declaration")
    schema, _, name = MATERIALISED.partition(".")
    after = journey["build the changed declaration"].observation

    assert f"Tables/{schema}/{name}" not in after.shortcuts
    assert name in after.relations
    for qualified in POINTED_AT:
        assert qualified in after.shortcuts


@weaver_test(remote=True)
def test_the_materialised_objects_row_stays_as_the_record_of_its_source(journey):
    """Marked deleted, it still names the workspace and catalogue mirrored."""

    journey.require("build the changed declaration")
    after = journey["build the changed declaration"].observation

    assert f"Tables/{MATERIALISED}" not in after.borrowed
    assert after.retired[f"Tables/{MATERIALISED}"] == journey.workspace.workspace
    assert "Tables/DWG.Customer" in after.borrowed


@weaver_test(remote=True)
def test_materialising_leaves_the_source_untouched(journey):
    journey.require("build the changed declaration")

    assert journey["build the changed declaration"].observation.source_rows == (
        journey["mirror"].observation.source_rows
    )
