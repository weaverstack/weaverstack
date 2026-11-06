"""Deploy the Catalogue Dashboard over one or more Weaver catalogues.

The Dashboard observes catalogues and takes no part in their lifecycle. Its
model and Report deploy through an ordinary Power BI Build without a catalogue,
and every catalogue is only read: no catalogue table is built and no catalogue
row is written.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from ..errors import CommandError, ConfigError
from ..representation import ReportAlias
from ..workspaces import CatalogueRef, Workspace

CREATED = "created"
UPDATED = "updated"
#: The Dashboard model's measure table and the measure every page ends with.
_FINGERPRINT = ("Dashboard measures", "Renderer")


@dataclass(frozen=True)
class DashboardItem(ReportAlias):
    kind: str
    name: str
    #: ``created`` or ``updated``; a dry run says what it would do.
    status: str
    item_id: str | None = None

    def to_mapping(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "item_id": self.item_id,
        }


@dataclass(frozen=True)
class CatalogueDashboardResult(ReportAlias):
    workspace: str
    #: The first catalogue read, as ``Workspace/Warehouse/Name``.
    catalogue: str
    name: str
    items: tuple[DashboardItem, ...] = ()
    #: The catalogue tables the model reads.
    sources: tuple[str, ...] = ()
    dry_run: bool = False
    status: str = "succeeded"
    errors: tuple[str, ...] = field(default=())
    #: Every catalogue read, in the order given.
    catalogues: tuple[str, ...] = ()
    #: ``directLake`` or ``import``.
    mode: str = "directLake"
    #: What the deployment could not finish, such as an Import source no
    #: connection reaches.
    warnings: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    def to_mapping(self) -> dict:
        return {
            "workspace": self.workspace,
            "catalogue": self.catalogue,
            "catalogues": list(self.catalogues or (self.catalogue,)),
            "mode": self.mode,
            "name": self.name,
            "items": [item.to_mapping() for item in self.items],
            "sources": list(self.sources),
            "dry_run": self.dry_run,
            "status": self.status,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def deploy_catalogue_dashboard(
    *,
    catalogue: str | Sequence[str] | None = None,
    name: str | None = None,
    workspace: str | None = None,
    workspace_config: str | Path | None = None,
    import_mode: bool = False,
    dry_run: bool = False,
    session=None,
) -> CatalogueDashboardResult:
    """Create or update the Catalogue Dashboard's SemanticModel and Report.

    ``catalogue`` is each catalogue read, ``Workspace/Warehouse/Name`` or
    ``Warehouse/Name`` in the Dashboard's workspace; it defaults to the
    configured ``catalogue:``. ``name`` is the Fabric item the model and Report
    deploy to in the Dashboard's workspace; it defaults to
    ``catalogue_dashboard:``. The model reads up to ten catalogues over Direct
    Lake; ``import_mode`` imports them instead, and is required for more.
    ``dry_run`` resolves the targets and the catalogues and changes nothing.
    """

    from ..dashboard_model import DIRECT_LAKE, DIRECT_LAKE_CATALOGUES, IMPORT
    from .workspace import operation_workspace

    base = operation_workspace(
        "catalogue-dashboard",
        workspace=workspace,
        workspace_config=workspace_config,
        session=session,
        needs_catalogue=False,
    )
    places = _sources(catalogue, base)
    mode = IMPORT if import_mode else DIRECT_LAKE
    if mode == DIRECT_LAKE and len(places) > DIRECT_LAKE_CATALOGUES:
        raise CommandError(
            f"The Catalogue Dashboard reads up to {DIRECT_LAKE_CATALOGUES} catalogues "
            f"over Direct Lake, and {len(places)} were given. Pass --ImportMode to "
            "import them instead."
        )
    references = tuple(reference for reference, *_ in places)
    name = name or base.catalogue_dashboard
    if not name:
        raise CommandError(
            "Name the Catalogue Dashboard: pass --name, or set catalogue_dashboard: "
            "in workspace-config.yml."
        )
    _refuse_configured_targets(base, name)
    from ..sessions.host import use_or_create_session

    def result(**values):
        return CatalogueDashboardResult(
            workspace=base.workspace,
            catalogue=references[0],
            catalogues=references,
            mode=mode,
            name=name,
            **values,
        )

    with use_or_create_session(session, workspace=base) as opened:
        with opened.task("Catalogue Dashboard", name):
            with opened.step("Check the catalogues", f"{len(places)} given"):
                sources = _require_sources(opened, base, places, mode)
            tables = tuple(f"_.{table}" for table in required_tables())
            with opened.step("Resolve the Dashboard's items", name):
                model, report = _existing_targets(opened, base, name)
            if dry_run:
                return result(
                    items=_outcomes(name, model, report, planned=True),
                    sources=tables,
                    dry_run=True,
                )
            built = _deploy(opened, base, name, sources, mode)
            if not built.succeeded:
                return result(
                    sources=tables,
                    status=built.status,
                    errors=tuple(
                        error.message or error.action_id for error in built.errors
                    ),
                )
            warnings = ()
            client = opened.semantic_model(name, workspace=base)
            unreached = ()
            if mode == IMPORT:
                with opened.step("Bind the Dashboard model's connections", name):
                    unreached = client.bind_data_sources().unreached
            if unreached:
                warnings = (
                    "No connection reaches "
                    + ", ".join(unreached)
                    + ". Create a cloud connection to each SQL endpoint and "
                    "deploy again, or set the model's credentials in Fabric and "
                    "refresh it.",
                )
            else:
                with opened.step("Refresh the Dashboard model", name):
                    # Direct Lake frames the catalogue tables; Import reads them.
                    client.refresh()
            deployed = (
                _find(opened, base, name, "SemanticModel"),
                _find(opened, base, name, "Report"),
            )
    return result(
        items=tuple(
            DashboardItem(
                item.kind,
                name,
                UPDATED if before is not None else CREATED,
                after.id,
            )
            for item, before, after in zip(
                _outcomes(name, None, None, planned=False),
                (model, report),
                deployed,
            )
        ),
        sources=tables,
        warnings=warnings,
    )


def _sources(catalogue, base: Workspace) -> list[tuple[str, str, str, str]]:
    """Each catalogue read: its reference, label, workspace and Warehouse."""

    from ..catalogues import labels_for

    values = [catalogue] if isinstance(catalogue, str) else list(catalogue or ())
    if not values and base.catalogue:
        values = [base.catalogue]
    if not values:
        raise CommandError(
            "Name the catalogue the Dashboard reads: pass --catalogue "
            "Workspace/Warehouse/Name, or set catalogue: in workspace-config.yml."
        )
    owners = []
    for value in values:
        try:
            parsed = CatalogueRef.parse(value)
        except ConfigError:
            raise CommandError(
                f"--catalogue must be Workspace/Warehouse/Name or Warehouse/Name, got {value!r}."
            ) from None
        owners.append((parsed.owner(base.workspace), parsed.name))
    seen = set()
    for owner, warehouse in owners:
        key = (owner.casefold(), warehouse.casefold())
        if key in seen:
            raise CommandError(
                f"{owner}/Warehouse/{warehouse} was given more than once. Pass each "
                "catalogue once."
            )
        seen.add(key)
    return [
        (f"{owner}/Warehouse/{warehouse}", label, owner, warehouse)
        for label, (owner, warehouse) in zip(labels_for(owners), owners)
    ]


def _refuse_configured_targets(base: Workspace, name: str) -> None:
    for item, declaration in base.targets.items():
        if (
            item.item_type in {"SemanticModel", "Report"}
            and declaration.physical.casefold() == name.casefold()
        ):
            raise CommandError(
                f"targets: deploys {item} to {declaration.physical}. Choose another "
                "name for the Catalogue Dashboard."
            )


def required_tables() -> tuple[str, ...]:
    """The catalogue tables the Dashboard model reads."""

    from ..dashboard_model import OPTIONAL, RELATIONS

    return tuple(sorted(set(RELATIONS.values()) - OPTIONAL))


def _require_sources(opened, base, places, mode):
    """Every catalogue as the model reads it, read at once and retried once.

    Every catalogue that cannot be read is named before anything changes.
    """

    from .joined import concurrently, retried

    def read(place):
        reference, label, owner, warehouse = place
        workspace = (
            base
            if owner.casefold() == base.workspace.casefold()
            else Workspace(workspace=owner)
        )

        def attempt():
            # A refusal is the catalogue's answer; only a failed read is retried.
            try:
                return _require_source(
                    opened, base, label, owner, warehouse, reference, mode
                )
            except CommandError as exc:
                return exc

        return retried(attempt, session=opened, workspace=workspace)

    outcomes = concurrently(places, read)
    failed = [
        str(each) if isinstance(each, CommandError) else f"{place[0]}: {each}"
        for place, each in zip(places, outcomes)
        if isinstance(each, Exception)
    ]
    if len(failed) == 1:
        raise CommandError(failed[0])
    if failed:
        raise CommandError("; ".join(failed))
    return outcomes


def _require_source(opened, base, label, owner, warehouse, reference, mode):
    """The catalogue as the model reads it, refusing one it cannot read."""

    from ..dashboard_model import IMPORT, DashboardSource, missing_columns
    from ..fabric.resources import ItemNotFoundError
    from ..targets import ItemRef, WarehouseTarget

    place = (
        base
        if owner.casefold() == base.workspace.casefold()
        else Workspace(workspace=owner)
    )
    try:
        item = opened.resolve_item(warehouse, item_type="Warehouse", workspace=place)
    except ItemNotFoundError as exc:
        raise CommandError(f"{reference} was not found. {exc}") from exc
    target = WarehouseTarget(warehouse=ItemRef(warehouse))
    rows = opened.query_tsql(
        "select t.name as table_name, c.name as column_name, ty.name as type_name "
        "from sys.tables t join sys.columns c on c.object_id = t.object_id "
        "join sys.types ty on ty.user_type_id = c.user_type_id "
        "where schema_name(t.schema_id) = N'_' order by t.name, c.column_id",
        target=target,
        workspace=place,
    )
    columns: dict[str, dict[str, str]] = {}
    for row in rows:
        columns.setdefault(str(row["table_name"]), {})[str(row["column_name"])] = str(
            row["type_name"]
        )
    wanted = required_tables()
    missing = [table for table in wanted if table not in columns]
    if len(missing) == len(wanted):
        raise CommandError(
            f"{reference} holds no Weaver catalogue. Build a project into it first."
        )
    if missing:
        listed = ", ".join(f"_.{table}" for table in missing)
        raise CommandError(
            f"{reference} has no {listed}. Build a project with this version of "
            "Weaver into that catalogue first."
        )
    source = DashboardSource(
        label=label,
        reference=reference,
        workspace=owner,
        workspace_id=item.workspace_id,
        warehouse=item.name,
        item_id=item.id,
        columns=columns,
    )
    absent = missing_columns(source)
    if absent:
        listed = "; ".join(
            f"_.{table}: {', '.join(names)}" for table, names in absent.items()
        )
        raise CommandError(
            f"{reference} lacks columns the Dashboard reads ({listed}). Build a "
            "project with this version of Weaver into that catalogue first."
        )
    server = None
    if mode == IMPORT:
        server = opened.resolver(place).sql_endpoint(target).server
    from dataclasses import replace

    return replace(source, server=server)


def _find(opened, base, name: str, kind: str):
    from ..fabric.resources import ItemNotFoundError

    try:
        return opened.resolve_item(name, item_type=kind, workspace=base)
    except ItemNotFoundError:
        return None


def _existing_targets(opened, base, name: str):
    """The model and Report already named ``name``, refusing any that is not ours."""

    model = _find(opened, base, name, "SemanticModel")
    report = _find(opened, base, name, "Report")
    if model is not None and not _is_dashboard(opened, base, model):
        raise CommandError(
            f"SemanticModel {name} is not a Catalogue Dashboard. Choose another name."
        )
    if report is not None:
        bound = (
            opened.report_item(report.name, workspace=base).get_binding() or {}
        ).get("datasetId")
        if model is None or str(bound).casefold() != str(model.id).casefold():
            raise CommandError(
                f"Report {name} does not read the Catalogue Dashboard model. Choose "
                "another name."
            )
    return model, report


def _is_dashboard(opened, base, model) -> bool:
    from urllib.parse import unquote

    from ..semantic_models.definition import decode_parts

    definition = opened.semantic_model(model.name, workspace=base).get_definition(
        format="TMDL"
    )
    table, measure = _FINGERPRINT
    return any(
        unquote(path) == f"definition/tables/{table}.tmdl"
        and re.search(rf"^\s*measure '?{measure}'?\s*=", data.decode("utf-8"), re.M)
        for path, data in decode_parts(definition).items()
    )


def _outcomes(name, model, report, *, planned: bool) -> tuple[DashboardItem, ...]:
    def status(existing):
        return UPDATED if existing is not None else CREATED

    return tuple(
        DashboardItem(
            kind,
            name,
            status(existing),
            getattr(existing, "id", None) if planned else None,
        )
        for kind, existing in (("SemanticModel", model), ("Report", report))
    )


def write_dashboard_project(root: Path, sources, mode: str) -> None:
    """Write the Dashboard as the ordinary Power BI project it deploys as."""

    from ..catalogue_dashboard import DASHBOARD_PROJECT, dashboard_files

    for relative, data in dashboard_files(sources, mode).items():
        path = root / DASHBOARD_PROJECT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _deploy(opened, base: Workspace, name: str, sources, mode: str):
    """Build the Dashboard project catalogue-free."""

    import yaml

    from ..catalogue_dashboard import DASHBOARD_ITEMS
    from . import build as building

    with tempfile.TemporaryDirectory(prefix="weaver-dashboard-") as temporary:
        root = Path(temporary)
        write_dashboard_project(root, sources, mode)
        config = root / "workspace-config.yml"
        config.write_text(
            yaml.safe_dump(
                {
                    "workspace": base.workspace,
                    "targets": {str(item): name for item in DASHBOARD_ITEMS},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return building.build(
            root,
            items=[str(item) for item in DASHBOARD_ITEMS],
            workspace_config=config,
            session=opened,
        )


__all__ = [
    "CatalogueDashboardResult",
    "DashboardItem",
    "deploy_catalogue_dashboard",
    "write_dashboard_project",
]
