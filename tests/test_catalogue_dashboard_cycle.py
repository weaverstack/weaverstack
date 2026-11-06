"""The Catalogue Dashboard deploys over catalogues, outside their lifecycle."""

import json
import re

import pytest
from support.dashboard_sources import dashboard_source, dashboard_sources
from support.weaver_test import weaver_test
from test_semantic_model_build_cycle import DefinitionClient
from test_semantic_source_build_cycle import SourceInventory

import weaver
from weaver.catalogue.tables import TABLES_BY_NAME
from weaver.catalogue_dashboard import (
    DASHBOARD,
    DASHBOARD_ITEMS,
    DASHBOARD_MODEL,
    DASHBOARD_REPORT,
    renderer_html,
    renderer_literal,
)
from weaver.dashboard_model import (
    DIRECT_LAKE,
    IMPORT,
    declared_columns,
    model_text,
    required_columns,
)
from weaver.declaration.repository import parse_item_repository
from weaver.errors import CommandError
from weaver.fabric.resolution import FabricResolver
from weaver.locations import Location
from weaver.operations.catalogue_dashboard import (
    required_tables,
    write_dashboard_project,
)
from weaver.semantic_models.definition import (
    decode_parts,
    encode_definition,
    encode_parts,
)
from weaver.semantic_models.objects import TmdlDefinition
from weaver.sessions import TestSession
from weaver.store import FilesystemStore
from weaver.workspaces import Workspace

HTML_CONTENT = "htmlContent443BE3AD55E043BF878BED274D3A6855"
#: Every measure lives here. Analysis Services reserves the name Measures.
MEASURE_TABLE = "Dashboard measures"

#: Every catalogue table the model reads, by model table.
SOURCES = {
    "Lineage node": "LineageNode",
    "Lineage edge": "LineageEdge",
    "Installation": "Installation",
    "Registry": "Registry",
    "Dependency": "Dependency",
    "Load status": "LoadStatus",
    "Log": "Log",
    "Load statistic": "LoadStatistic",
    "Test status": "TestStatus",
    "Test dictionary": "TestDictionary",
    "Schema dictionary": "SchemaDictionary",
    "Table dictionary": "TableDictionary",
    "Folder dictionary": "FolderDictionary",
    "Column dictionary": "ColumnDictionary",
    "Key dictionary": "KeyDictionary",
    "Foreign key dictionary": "ForeignKeyDictionary",
    "Semantic model": "SemanticModel",
    "Semantic model table": "SemanticModelTable",
    "Semantic model column": "SemanticModelColumn",
    "Semantic model measure": "SemanticModelMeasure",
    "Semantic model relationship": "SemanticModelRelationship",
    "Shortcut": "Shortcut",
}

#: The page measure each Report page shows, in page order.
PAGES = {
    "workspaces": "Workspaces page",
    "overview": "Overview page",
    "health": "Health page",
    "orchestration": "Orchestration page",
    "performance": "Performance page",
    "gantt": "Gantt page",
    "entities": "Entity dictionary page",
    "semantic": "Semantic model page",
}

#: The pages that refresh themselves, because they show settling work.
LIVE = {"overview", "health", "orchestration", "performance", "gantt"}

#: Every measure, by display folder.
MEASURES = {
    "Health": {
        "Failed loads",
        "Rejected loads",
        "Pending loads",
        "Failed tests",
        "Latest processed completion",
        "Observed at",
    },
    "Estate": {"Items", "Installed objects", "Processed log records"},
    "Data": {
        "Catalogue data",
        "Lineage data",
        "Node data",
        "Status data",
        "Build data",
        "Workflow data",
        "Run data",
        "Log data",
        "Statistic data",
        "Metadata data",
        "Semantic data",
        "Estate data",
    },
    "Pages": {"Renderer", *PAGES.values()},
}


def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return root


def parse(root):
    return parse_item_repository(Location(root.as_posix()))


def dashboard_repository(tmp_path, sources=None, mode=DIRECT_LAKE):
    root = project(tmp_path)
    write_dashboard_project(
        root, dashboard_sources() if sources is None else sources, mode
    )
    return parse(root)


def dashboard_model(tmp_path, sources=None, mode=DIRECT_LAKE):
    return dashboard_repository(tmp_path, sources, mode).semantic_models[
        DASHBOARD_MODEL
    ]


def measures(parts):
    found = {}
    for table in TmdlDefinition(parts).model.tables:
        for measure in table.measures:
            found[measure.name] = (
                table.name,
                measure.displayFolder,
                measure.expression,
            )
    return found


@weaver_test()
def test_the_dashboard_is_an_ordinary_power_bi_project(tmp_path):
    repository = dashboard_repository(tmp_path)

    assert set(repository.powerbi_projects[DASHBOARD].items) == set(DASHBOARD_ITEMS)
    assert repository.reports[DASHBOARD_REPORT].model == DASHBOARD_MODEL
    # Every catalogue table is generated with its source; none is bound by Build.
    assert not repository.semantic_models[DASHBOARD_MODEL].source_references
    assert required_tables() == tuple(sorted(SOURCES.values()))


@pytest.mark.parametrize("mode", [DIRECT_LAKE, IMPORT])
@weaver_test()
def test_both_modes_expose_one_set_of_measures_over_every_catalogue(tmp_path, mode):
    sources = dashboard_sources(3)
    parts = dashboard_model(tmp_path, sources, mode).parts
    model = TmdlDefinition(parts).model
    tables = {table.name: table for table in model.tables}
    found = measures(parts)

    assert set(found) == set().union(*MEASURES.values())
    if mode == DIRECT_LAKE:
        # One hidden table per catalogue and relation, over OneLake.
        for source in sources:
            for name, relation in SOURCES.items():
                table = tables[f"{name} {source.alias}"]
                assert table.isHidden
                (partition,) = table.partitions
                assert partition.mode == "directLake"
        expressions = model.expressions
        assert {e.name for e in expressions} == {
            f"Catalogue {s.alias}" for s in sources
        }
    else:
        # One table per relation, a partition per catalogue, tagged with it.
        for name in SOURCES:
            table = tables[name]
            assert [p.name for p in table.partitions] == [
                f"{name} {s.alias}" for s in sources
            ]
            assert {"Catalogue", "Catalogue code"} <= {c.name for c in table.columns}
    # The page measures bind the same names in both modes.
    for page, measure in PAGES.items():
        assert f'"{page}"' in found[measure][2]


@weaver_test()
def test_a_measure_reads_every_catalogue_and_reduces_across_them():
    sources = dashboard_sources(2)
    direct = model_text(sources, DIRECT_LAKE)
    imported = model_text(sources, IMPORT)
    a, b = (source.alias for source in sources)

    workflows = direct[direct.index("measure 'Workflow data'") :]
    workflows = workflows[: workflows.index("displayFolder")]
    # One union of both catalogues' rows, then one GROUPBY and one TOPN over it.
    assert f"'Log {a}'" in workflows and f"'Log {b}'" in workflows
    assert workflows.count("UNION(") == 2
    assert workflows.count("TOPN(40") == 1
    assert '"@catalogue", "Team1"' in workflows and '"@code", "2"' in workflows
    # Import reads the combined table and its catalogue column.
    imported_workflows = imported[imported.index("measure 'Workflow data'") :]
    assert "'Log'[Catalogue]" in imported_workflows
    assert (
        "UNION(" not in imported_workflows[: imported_workflows.index("displayFolder")]
    )


@weaver_test()
def test_the_measures_read_only_columns_every_catalogue_declares():
    for table, columns in required_columns().items():
        assert set(columns) <= set(declared_columns(table)), table


@weaver_test()
def test_each_catalogues_tables_keep_their_names_whatever_the_order_given():
    first, second = dashboard_sources(2)
    assert first.alias == dashboard_source("Team1", index=1).alias != second.alias


@weaver_test()
def test_an_authored_model_named_like_the_dashboard_builds_like_any_other(tmp_path):
    from weaver.onboarding.project import semantic_extension
    from weaver.operations.build import _item_bindings
    from weaver.workspaces import TargetDeclaration

    root = project(tmp_path)
    authored = root / "PowerBI/Catalogue Dashboard/Catalogue Dashboard.tmdl"
    authored.parent.mkdir(parents=True)
    authored.write_text(semantic_extension(), encoding="utf-8")
    workspace = Workspace(
        workspace="Demo",
        catalogue="Warehouse/Catalogue",
        catalogue_dashboard="Estate Dashboard",
        targets={
            "SemanticModel/Catalogue Dashboard": TargetDeclaration("Estate"),
            "Warehouse/Curated": TargetDeclaration("Curated"),
        },
    )

    selected = _item_bindings("PowerBI", workspace, repository=parse(root))
    unscoped = _item_bindings(None, workspace, repository=parse(root))

    assert [str(b.item) for b in selected.entries] == [str(DASHBOARD_MODEL)]
    assert {str(b.item) for b in unscoped.entries} == {
        str(DASHBOARD_MODEL),
        "Warehouse/Curated",
    }


@weaver_test()
def test_every_measure_lives_in_one_measure_table_by_display_folder(tmp_path):
    model = dashboard_model(tmp_path)
    found = measures(model.parts)

    assert {
        folder: {name for name, (_, f, _) in found.items() if f == folder}
        for folder in MEASURES
    } == MEASURES
    assert set(found) == set().union(*MEASURES.values())
    assert {table for table, _, _ in found.values()} == {MEASURE_TABLE}
    table = TmdlDefinition(model.parts).model.tables[MEASURE_TABLE]
    assert "Weaver.MeasureTable" in [a.name for a in table.annotations]


@weaver_test()
def test_the_measures_quote_every_table_and_avoid_reserved_names(tmp_path):
    """LOG is a function and ROWS is reserved, so an unquoted table breaks DAX."""

    model = dashboard_model(tmp_path)
    tables = {table.name for table in TmdlDefinition(model.parts).model.tables}
    for name, (_, _, expression) in measures(model.parts).items():
        if name == "Renderer":
            continue
        assert not re.search(r"\bVAR\s+rows\b", expression, re.IGNORECASE), name
        for table in tables:
            unquoted = re.search(rf"(?<!['\w]){re.escape(table)}\[", expression)
            assert unquoted is None, f"{name} reads {table} unquoted"
        # No column name holds a quote, so a quoted table name never lands in one.
        assert not re.search(r"\[[^\]\"]*'[^\]\"]*\]", expression), name


@weaver_test()
def test_the_renderer_reaches_the_model_as_one_string_literal(tmp_path):
    expression = measures(dashboard_model(tmp_path).parts)["Renderer"][2].strip()

    assert expression.startswith('"<style>') and expression.endswith('</script>"')
    inner = expression[1:-1]
    assert '"' not in inner.replace('""', "")
    html = inner.replace('""', '"')
    assert html == renderer_html()
    assert html.count("</script>") == 1 and html.count("</style>") == 1
    # Every script, in name order, inside one function.
    assert "function focusWindow(" in html and "function assessHealth(" in html
    assert html.index("function parsePayload(") < html.index("function start(")
    assert "--paper:" in html
    with pytest.raises(AssertionError, match="</script"):
        renderer_literal("", "'</script>'")


@weaver_test()
def test_each_page_shows_one_html_content_visual_over_its_page_measure(tmp_path):
    repository = dashboard_repository(tmp_path)
    parts = repository.reports[DASHBOARD_REPORT].parts
    names = measures(repository.semantic_models[DASHBOARD_MODEL].parts)

    report = json.loads(parts["definition/report.json"])
    assert report["publicCustomVisuals"] == [HTML_CONTENT]
    pages = json.loads(parts["definition/pages/pages.json"])
    assert pages["pageOrder"] == list(PAGES)
    for page, measure in PAGES.items():
        visuals = [
            json.loads(content)
            for path, content in parts.items()
            if re.fullmatch(rf"definition/pages/{page}/visuals/\w+/visual\.json", path)
        ]
        # The page draws everything, its item choosers included, in one visual.
        (visual,) = visuals
        settings = json.loads(parts[f"definition/pages/{page}/page.json"])
        assert "filterConfig" not in settings
        assert visual["visual"]["visualType"] == HTML_CONTENT
        (projection,) = visual["visual"]["query"]["queryState"]["content"][
            "projections"
        ]
        field = projection["field"]["Measure"]
        assert field["Expression"]["SourceRef"]["Entity"] == MEASURE_TABLE
        assert field["Property"] == measure and measure in names
        # The data element names its page, then the renderer reads it.
        expression = names[measure][2]
        assert (
            f'"page" & UNICHAR(57345) & "name" & UNICHAR(57346) & "{page}"'
            in expression
        )
        assert expression.index('id=""wd-data""') < expression.rindex("[Renderer]")
        assert "SUBSTITUTE(" in expression and '"<", UNICHAR(57344))' in expression
        assert ("pageRefresh" in settings.get("objects", {})) is (page in LIVE)


# --- weaver catalogue-dashboard ---------------------------------------------


class CatalogueSource(TestSession):
    """Answers the source catalogue's table list and each table's columns."""

    def __init__(self, *, tables, missing=(), **options):
        super().__init__(**options)
        self.tables = tables
        self.missing = set(missing)
        self.read = []

    def query_tsql(self, statement, **options):
        self.read.append(statement)
        if "sys.tables" in statement:
            return [
                {"table_name": table, "column_name": column, "type_name": kind}
                for table in sorted(self.tables)
                for column, kind in declared_columns(table).items()
                if (table, column) not in self.missing
            ]
        named = re.search(r"TABLE_NAME = N?'(\w+)'", statement)
        if named and "INFORMATION_SCHEMA.COLUMNS" in statement:
            return [
                {"column_name": column, "data_type": "varchar"}
                for column in TABLES_BY_NAME[named.group(1)].public_columns
            ]
        return super().query_tsql(statement, **options)


class DashboardDefinition(DefinitionClient):
    """A deployed model that is, or is not, a Catalogue Dashboard."""

    def __init__(self, *, ours=True):
        super().__init__()
        self.ours = ours

    def get_definition(self, format="TMSL"):
        if format == "TMSL":
            return super().get_definition()
        self.calls.append(("get_definition", format))
        table = "Dashboard measures" if self.ours else "Sales"
        return encode_parts(
            {
                "definition.pbism": b"{}",
                f"definition/tables/{table.replace(' ', '%20')}.tmdl": (
                    f"table '{table}'\n\tmeasure 'Renderer' = 1\n".encode()
                ),
            }
        )


def dashboard_session(
    *, existing=True, tables=None, ours=True, workspace=None, missing=(), held=()
):
    from test_report_build_cycle import ReportBoundary

    workspace = workspace or Workspace(
        workspace="Demo",
        catalogue="Warehouse/Catalogue",
        catalogue_dashboard="Estate Dashboard",
    )
    held = [("Warehouse", "Catalogue"), *held]
    if existing:
        held += [("SemanticModel", "Estate Dashboard"), ("Report", "Estate Dashboard")]
    session = CatalogueSource(
        tables=set(required_tables() if tables is None else tables),
        missing=missing,
        workspace=workspace,
        store=FilesystemStore(),
        resolver=FabricResolver(workspace, client=SourceInventory("Demo", held)),
    )
    model = DashboardDefinition(ours=ours)
    session.answer_semantic_model("Demo", "Estate Dashboard", model)
    report = ReportBoundary([])
    if existing:
        model_id = session.resolve_item(
            "Estate Dashboard", item_type="SemanticModel", workspace=workspace
        ).id
        bound = report.get_binding
        report.get_binding = lambda: (
            {"datasetId": model_id} if report.definition is None else bound()
        )
    session.answer_report("Demo", "Estate Dashboard", report)
    execute = session.execute_mutation

    # Fabric answers readback with what Build asked for, as a deployment that kept it.
    def deployed_as_requested(plan, payloads=None, **options):
        for name, content in (payloads or {}).items():
            if name.endswith(".semantic_model.json"):
                requested = json.loads(content)["requested"]
                model.definition = encode_definition(
                    {"compatibilityLevel": 1606, "model": requested}
                )
        return execute(plan, payloads, **options)

    session.execute_mutation = deployed_as_requested
    return session, model, report


@weaver_test()
def test_the_dashboard_deploys_over_the_catalogue_and_only_reads_it():
    session, model, report = dashboard_session()

    result = weaver.deploy_catalogue_dashboard(session=session)

    assert result.succeeded, result.errors
    assert (result.workspace, result.catalogue, result.name, result.mode) == (
        "Demo",
        "Demo/Warehouse/Catalogue",
        "Estate Dashboard",
        DIRECT_LAKE,
    )
    assert result.catalogues == ("Demo/Warehouse/Catalogue",)
    assert [(i.kind, i.status) for i in result.items] == [
        ("SemanticModel", "updated"),
        ("Report", "updated"),
    ]
    calls = [method for method, _ in model.calls]
    assert "update_definition" in calls and calls[-1] == "refresh"
    submitted = decode_parts(
        next(value for method, value in model.calls if method == "update_definition")[
            "definition"
        ]
    )
    catalogue = session.resolve_item("Catalogue", item_type="Warehouse")
    expressions = submitted["definition/expressions.tmdl"].decode()
    assert (
        "https://onelake.dfs.fabric.microsoft.com/"
        f"{catalogue.workspace_id}/{catalogue.id}" in expressions
    )
    definition = TmdlDefinition(submitted).model
    (node,) = [t for t in definition.tables if t.name.startswith("Lineage node ")]
    (partition,) = node.partitions
    assert partition.mode == "directLake"
    assert node.isHidden
    assert set(measures(submitted)) == set().union(*MEASURES.values())
    assert report.calls == ["update", "read"]
    # The catalogue is read and never written: no table is built, no row changes.
    assert not session.tsql
    assert all(
        statement.lstrip().lower().startswith("select") for statement in session.read
    )
    assert not session.spark_sql and not session.python


@weaver_test()
def test_a_dry_run_resolves_everything_and_changes_nothing():
    session, model, report = dashboard_session(existing=False)

    result = weaver.deploy_catalogue_dashboard(dry_run=True, session=session)

    assert result.dry_run and result.succeeded
    assert [(i.kind, i.status) for i in result.items] == [
        ("SemanticModel", "created"),
        ("Report", "created"),
    ]
    assert result.sources == tuple(f"_.{t}" for t in sorted(SOURCES.values()))
    assert not model.calls and not report.calls
    assert not session.tsql
    mapping = result.to_mapping()
    assert (mapping["mode"], mapping["catalogues"]) == (
        DIRECT_LAKE,
        ["Demo/Warehouse/Catalogue"],
    )


@weaver_test()
def test_a_first_deploy_builds_the_project_without_a_catalogue(monkeypatch):
    import yaml

    session, model, _report = dashboard_session(existing=False)
    seen = {}

    def build(source, *, items, workspace_config, session):
        seen["items"] = items
        seen["config"] = yaml.safe_load(open(workspace_config, encoding="utf-8"))
        seen["files"] = sorted(
            str(path.relative_to(source)) for path in source.rglob("*.tmdl")
        )[:1]
        return weaver.BuildResult(
            source=str(source),
            items=tuple(items),
            bundle_id=None,
            installation=None,
            bundle_path=None,
            status="succeeded",
        )

    monkeypatch.setattr("weaver.operations.build.build", build)
    monkeypatch.setattr(
        session,
        "resolve_item",
        _created_after_build(session.resolve_item, seen),
    )

    result = weaver.deploy_catalogue_dashboard(session=session)

    assert seen["items"] == [str(DASHBOARD_MODEL), str(DASHBOARD_REPORT)]
    assert seen["config"] == {
        "workspace": "Demo",
        "targets": {
            str(DASHBOARD_MODEL): "Estate Dashboard",
            str(DASHBOARD_REPORT): "Estate Dashboard",
        },
    }
    assert [(i.kind, i.status) for i in result.items] == [
        ("SemanticModel", "created"),
        ("Report", "created"),
    ]
    assert [method for method, _ in model.calls] == ["refresh"]


def _created_after_build(resolve, seen):
    """Fabric holds the Dashboard's items only once Build has created them."""

    from types import SimpleNamespace

    from weaver.fabric.resources import ItemNotFoundError

    def resolved(item, *, item_type, workspace=None):
        if item == "Estate Dashboard":
            if "items" not in seen:
                raise ItemNotFoundError(f"{item_type} {item!r} was not found")
            return SimpleNamespace(id=f"{item_type}-id", name=item)
        return resolve(item, item_type=item_type, workspace=workspace)

    return resolved


@pytest.mark.parametrize(
    ("options", "named"),
    [
        (
            {"catalogue": ["Demo/Warehouse/Catalogue", "demo/Warehouse/catalogue"]},
            "given more than once",
        ),
        (
            {"catalogue": [f"Team{i}/Warehouse/Weaver" for i in range(11)]},
            "Pass --ImportMode",
        ),
        ({"catalogue": "Lakehouse/Catalogue"}, "Workspace/Warehouse/Name"),
    ],
    ids=["the same catalogue twice", "eleven over Direct Lake", "not a Warehouse"],
)
@weaver_test()
def test_a_catalogue_set_the_dashboard_cannot_read_is_refused_first(options, named):
    session, model, _report = dashboard_session()

    with pytest.raises(CommandError, match=named):
        weaver.deploy_catalogue_dashboard(session=session, **options)
    assert not model.calls and not session.read


@weaver_test()
def test_catalogues_in_other_workspaces_are_read_where_they_are():
    session, _model, _report = dashboard_session(
        existing=False, held=[("Warehouse", "Other")]
    )

    result = weaver.deploy_catalogue_dashboard(
        catalogue=["Demo/Warehouse/Other", "Warehouse/Catalogue"],
        dry_run=True,
        session=session,
    )

    assert result.workspace == "Demo"
    assert result.catalogues == ("Demo/Warehouse/Other", "Demo/Warehouse/Catalogue")
    assert result.catalogue == "Demo/Warehouse/Other"


@weaver_test()
def test_a_catalogue_missing_a_column_the_dashboard_reads_is_named():
    session, model, _report = dashboard_session(
        missing={("LineageNode", "Is mirrored")}
    )

    with pytest.raises(CommandError, match=r"_\.LineageNode: Is mirrored"):
        weaver.deploy_catalogue_dashboard(session=session)
    assert not model.calls


@weaver_test()
def test_explicit_arguments_override_configuration():
    session, _model, _report = dashboard_session(existing=False)
    session._resolver = FabricResolver(
        session.workspace,
        client=SourceInventory("Demo", [("Warehouse", "Other")]),
    )

    result = weaver.deploy_catalogue_dashboard(
        catalogue="Demo/Warehouse/Other", name="Ops", dry_run=True, session=session
    )

    assert (result.catalogue, result.name) == ("Demo/Warehouse/Other", "Ops")


@weaver_test()
def test_without_a_name_the_feature_stays_off():
    session, _model, _report = dashboard_session(
        workspace=Workspace(workspace="Demo", catalogue="Warehouse/Catalogue")
    )
    with pytest.raises(CommandError, match="Name the Catalogue Dashboard"):
        weaver.deploy_catalogue_dashboard(session=session)


@weaver_test()
def test_a_warehouse_that_is_no_catalogue_is_refused():
    session, model, _report = dashboard_session(tables=set())

    with pytest.raises(CommandError, match="holds no Weaver catalogue"):
        weaver.deploy_catalogue_dashboard(session=session)
    assert not model.calls


@weaver_test()
def test_a_catalogue_without_the_dashboards_tables_is_refused():
    session, model, _report = dashboard_session(
        tables=set(required_tables()) - {"LineageNode", "LineageEdge"}
    )

    with pytest.raises(CommandError, match="has no _.LineageEdge, _.LineageNode"):
        weaver.deploy_catalogue_dashboard(session=session)
    assert not model.calls


@weaver_test()
def test_an_unrelated_model_of_that_name_is_refused_before_any_change():
    session, model, report = dashboard_session(ours=False)

    with pytest.raises(CommandError, match="is not a Catalogue Dashboard"):
        weaver.deploy_catalogue_dashboard(session=session)
    assert [method for method, _ in model.calls] == ["get_definition"]
    assert not report.calls


@weaver_test()
def test_a_configured_target_of_that_name_is_refused():
    from weaver.workspaces import TargetDeclaration

    session, model, _report = dashboard_session(
        workspace=Workspace(
            workspace="Demo",
            catalogue="Warehouse/Catalogue",
            catalogue_dashboard="Estate Dashboard",
            targets={"SemanticModel/Sales": TargetDeclaration("Estate Dashboard")},
        )
    )
    with pytest.raises(CommandError, match="targets: deploys SemanticModel/Sales"):
        weaver.deploy_catalogue_dashboard(session=session)
    assert not model.calls


@weaver_test()
def test_a_catalogue_that_was_never_a_mirror_is_read_without_one():
    from dataclasses import replace

    held, never = dashboard_sources(2)
    never = replace(
        never, columns={t: c for t, c in never.columns.items() if t != "Mirror"}
    )
    both = model_text([held, never], DIRECT_LAKE)
    assert f"table 'Mirror {held.alias}'" in both
    assert f"table 'Mirror {never.alias}'" not in both
    status = both[both.index("measure 'Status data'") :]
    assert f"'Mirror {held.alias}'" in status[: status.index("displayFolder")]

    neither = model_text([never], IMPORT)
    assert "table 'Mirror'" not in neither
    status = neither[neither.index("measure 'Status data'") :]
    assert 'FILTER(ROW("@catalogue", "", "@code", ""' in status
