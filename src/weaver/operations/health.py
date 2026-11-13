"""Public ``weaver.health(...)`` operation.

Every read is over TDS or OneLake. Health executes no authored load or test
Python, so it takes no Environment, and a Warehouse-only request starts no Livy
session.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from ..catalogue.tables import (
    DEPENDENCY,
    FOLDER_DICTIONARY,
    INSTALLATION,
    LOAD_STATUS,
    MIRROR,
    REGISTRY,
    SEMANTIC_MODEL,
    SEMANTIC_MODEL_TABLE,
    SEMANTIC_MODEL_TEST,
    SHORTCUT,
    TABLE_DICTIONARY,
    TEST_DICTIONARY,
    TEST_STATUS,
)
from ..declaration.model import WeaverItemId
from ..health import HealthReport, JoinedHealthReport, assess, resolve_as_of
from .items import installed_targets, requested_items
from .workspace import operation_workspace

#: Catalogue tables needed for topology and current lifecycle state.
HEALTH_TABLES = (
    INSTALLATION,
    REGISTRY,
    TABLE_DICTIONARY,
    FOLDER_DICTIONARY,
    TEST_DICTIONARY,
    DEPENDENCY,
    SEMANTIC_MODEL,
    SEMANTIC_MODEL_TABLE,
    SEMANTIC_MODEL_TEST,
    SHORTCUT,
    MIRROR,
    LOAD_STATUS,
    TEST_STATUS,
)

#: Mirrored catalogues contribute only current load state.
SOURCE_TABLES = (LOAD_STATUS,)

# Each whole-catalogue read uses one relational TDS request.
_DISCOVERY_READERS = 64


def health(
    items: str | Sequence[str] | None = None,
    *,
    as_of: str | datetime | None = None,
    workspace: str | None = None,
    catalogue: str | Sequence[str] | None = None,
    workspace_config: str | Path | None = None,
    inventories: bool = True,
    session=None,
) -> "HealthReport | JoinedHealthReport":
    """Report the installed estate's operational health.

    ``catalogue`` names one catalogue, or several as ``Workspace/Warehouse/Name``.
    Several are read together and joined where a physical shortcut in one lands
    on an object another installs. Each is reported in the order given, and an
    object behind a source in another catalogue is reported as behind. One that
    cannot be read is reported in its place with the reason. ``items`` then
    names ``Workspace/Kind/Name`` for an item outside this workspace's
    catalogue, and a bare workspace name every item of its catalogue.

    ``items`` restricts the subjects reported on. With none, every target the
    catalogue binds an item to. Managed ancestry outside the selection is still
    read, because whether a selected object is behind its sources is a question
    about the whole graph.

    ``as_of`` is the oldest acceptable settled load time and defaults to one day
    before the operation started. It must include a timezone.

    ``inventories`` reads each selected target's physical state, so a certified
    object that is not there is reported. It also checks that each selected
    installation still names its Fabric item, and an inconsistent one is
    reported without stopping the other checks. Turning it off leaves Build
    health to what the catalogue contradicts about itself.
    """

    started = datetime.now(timezone.utc)
    if not isinstance(catalogue, (str, type(None))) and len(list(catalogue)) > 1:
        return _joined_health(
            items,
            tuple(catalogue),
            as_of=as_of,
            workspace=workspace,
            workspace_config=workspace_config,
            inventories=inventories,
            session=session,
            started=started,
        )
    if not isinstance(catalogue, (str, type(None))):
        catalogue = next(iter(catalogue), None)
    requested = requested_items(items, what="health")
    resolved = operation_workspace(
        "health",
        workspace=workspace,
        catalogue=catalogue,
        workspace_config=workspace_config,
        session=session,
    )
    from ..sessions.host import use_or_create_session

    with use_or_create_session(session, workspace=resolved) as opened:
        with opened.task("Health", ", ".join(map(str, requested)) or "whole estate"):
            return run_health(
                opened,
                workspace=resolved,
                items=requested,
                as_of=resolve_as_of(as_of, started=started),
                generated_at=started,
                inventories=inventories,
            )


def run_health(
    session,
    *,
    workspace,
    items: Sequence[WeaverItemId] = (),
    as_of: datetime,
    generated_at: datetime,
    inventories: bool = True,
) -> HealthReport:
    catalogue, source = _read(session, workspace)
    return _report(
        session,
        workspace=workspace,
        catalogue=catalogue,
        source=source,
        items=items,
        as_of=as_of,
        generated_at=generated_at,
        inventories=inventories,
    )


def _read(session, workspace, *, steps: bool = True):
    """A catalogue and, where it mirrors one, its source catalogue.

    Without ``steps`` the reads are not framed, for a caller reading several
    catalogues at once.
    """

    from contextlib import nullcontext

    from ..catalogue.connection import catalogue_connection
    from ..catalogue.state import read_installed_catalogue

    def step(name):
        return session.step(name) if steps else nullcontext()

    connection = catalogue_connection(session, workspace)
    with step("Read catalogue"):
        # Read current state and its supporting statistics together.
        catalogue = read_installed_catalogue(
            connection, tables=HEALTH_TABLES, load_history=True
        )

    source = None
    if catalogue.mirrors:
        from .mirror import mirrored_source

        with step("Read the mirrored catalogue"):
            # Mirrored load state comes from the catalogue where rows are written.
            source = mirrored_source(
                catalogue,
                workspace=workspace,
                session=session,
                operation="health",
                tables=SOURCE_TABLES,
                history=True,
            )
    return catalogue, source


def _report(
    session,
    *,
    workspace,
    catalogue,
    source,
    items: Sequence[WeaverItemId],
    as_of: datetime,
    generated_at: datetime,
    inventories: bool,
) -> HealthReport:
    seen = _observe(
        session,
        workspace=workspace,
        catalogue=catalogue,
        items=items,
        inventories=inventories,
    )
    return assess(
        catalogue,
        as_of=as_of,
        generated_at=generated_at,
        targets=seen.targets,
        items=seen.items or None,
        inventories=seen.inventories,
        source=source,
        installation_faults=seen.installation_faults,
    )


def _observe(
    session, *, workspace, catalogue, items, inventories: bool, steps: bool = True
):
    """The selected targets, what they hold, and installations that no longer
    name their Fabric item."""

    from contextlib import nullcontext

    from ..health import Observed

    def step(name):
        return session.step(name) if steps else nullcontext()

    dag = catalogue.dag()
    # Report physical targets bound by the catalogue's installations.
    selected = (
        dag.targets
        if not items
        else tuple(
            dict.fromkeys(
                installed_targets(dag, items, catalogue=workspace.catalogue).values()
            )
        )
    )
    read = {}
    faults = {}
    if inventories:
        with step("Check installed items"):
            faults = _installation_faults(
                session,
                workspace=workspace,
                catalogue=catalogue,
                dag=dag,
                items=tuple(items),
                targets=selected,
            )
        with step("Read installed objects"):
            # A target whose item was replaced is reported, not read by name.
            broken = {dag.installations[item] for item in faults}
            read = _inventories(
                session,
                workspace=workspace,
                targets=tuple(target for target in selected if target not in broken),
                dag=dag,
            )
    return Observed(
        targets=selected if items else None,
        items=tuple(items),
        inventories=read,
        installation_faults=faults,
    )


def _joined_health(
    items,
    catalogues: Sequence[str],
    *,
    as_of,
    workspace,
    workspace_config,
    inventories: bool,
    session,
    started: datetime,
):
    from ..catalogues import Member
    from ..health import Unread, assess_joined
    from ..sessions.host import use_or_create_session
    from .joined import concurrently, requested_by_label, resolve_places, retried

    home, places = resolve_places(
        "health",
        catalogues,
        workspace=workspace,
        workspace_config=workspace_config,
        session=session,
    )
    requested = (
        {} if items is None else requested_by_label("health", items, places, home)
    )
    resolved_as_of = resolve_as_of(as_of, started=started)

    with use_or_create_session(session, workspace=home) as opened:
        with opened.task("Health", f"{len(places)} catalogues"):

            def read(place):
                """The catalogue as a member, what its targets hold, and why
                either could not be had."""

                with opened.concurrent_substep(f"Read {place.reference}"):
                    try:
                        catalogue, source = retried(
                            lambda: _read(opened, place.workspace, steps=False),
                            session=opened,
                            workspace=place.workspace,
                        )
                    except Exception as exc:  # noqa: BLE001 - reported in place
                        return None, None, f"Its catalogue could not be read: {exc}"
                    try:
                        dag = catalogue.dag()
                    except Exception as exc:  # noqa: BLE001 - reported in place
                        return (
                            None,
                            None,
                            f"Its catalogue could not be interpreted: {exc}",
                        )
                    member = Member(
                        label=place.label,
                        workspace=place.workspace.workspace,
                        catalogue_name=place.catalogue_name,
                        catalogue=catalogue,
                        dag=dag,
                        source=source,
                    )
                    if requested and place.label not in requested:
                        # Context only: its graph and load state are what is used.
                        return member, None, None
                    try:
                        seen = retried(
                            lambda: _observe(
                                opened,
                                workspace=place.workspace,
                                catalogue=catalogue,
                                items=requested.get(place.label, ()),
                                inventories=inventories,
                                steps=False,
                            ),
                            session=opened,
                            workspace=place.workspace,
                        )
                    except Exception as exc:  # noqa: BLE001 - reported in place
                        return (
                            member,
                            None,
                            f"Its targets could not be inventoried: {exc}",
                        )
                return member, seen, None

            with opened.step(f"Read {len(places)} catalogues"):
                outcomes = concurrently(
                    places, read, workers=_DISCOVERY_READERS, session=opened
                )
            entries, observed, failures = [], {}, {}
            for place, (member, seen, failure) in zip(places, outcomes):
                if member is None:
                    entries.append(
                        Unread(
                            place.label,
                            place.workspace.workspace,
                            place.reference,
                            failure,
                        )
                    )
                    continue
                entries.append(member)
                if seen is not None:
                    observed[place.label] = seen
                if failure is not None:
                    failures[place.label] = failure
            return assess_joined(
                entries,
                as_of=resolved_as_of,
                generated_at=started,
                observed=observed,
                # With items named, the other catalogues give context only.
                reported=tuple(requested) or None,
                failures=failures,
            )


def _installation_faults(session, *, workspace, catalogue, dag, items, targets):
    """Why each selected installation no longer names its Fabric item, by item."""

    from ..catalogue.installation import check_installations, recorded_installation

    chosen = set(items) if items else set(dag.installations)
    rows = {
        (item.item_type, item.item_name): row
        for item, target in dag.installations.items()
        if item in chosen
        and target in targets
        and (row := recorded_installation(catalogue, item)) is not None
    }
    if not rows:
        return {}
    _, faults = check_installations(rows.values(), resolver=session.resolver(workspace))
    return {WeaverItemId(*key): str(fault) for key, fault in faults.items()}


def _inventories(session, *, workspace, targets, dag):
    """Read each selected target's physical state without starting Spark.

    Warehouse state comes over TDS and Lakehouse state from storage. Lakehouse
    views are therefore not listed; see
    :meth:`weaver.health._Assessment._absent_from_inventory`.
    """

    from ..build_bundle.prune import read_lakehouse_inventory, read_warehouse_inventory
    from ..build_bundle.targets import BoundTarget
    from ..targets import WAREHOUSE_TARGET, ItemRef, WarehouseTarget

    bound_items = {}
    for item, target in dag.installations.items():
        bound_items.setdefault(target, item)

    found = {}
    for target in targets:
        if not target.is_lakehouse and target.kind != WAREHOUSE_TARGET:
            # Power BI objects live in their definitions, which Build reads back.
            continue
        item = bound_items.get(target)
        bound = BoundTarget(
            id=f"{target.kind}-{target.name}",
            kind=target.kind,
            item_id=target.name,
            item_name=target.name,
            workspace_name=workspace.workspace,
            logical_item_type=None if item is None else item.item_type,
            logical_item_name=None if item is None else item.item_name,
        )
        if target.is_lakehouse:
            found[target] = read_lakehouse_inventory(
                bound,
                resolver=session.resolver(workspace),
                store=session.transport_store(workspace),
            )
        else:
            found[target] = read_warehouse_inventory(
                bound,
                sql=session.sql_executor(
                    WarehouseTarget(warehouse=ItemRef.parse(target.name)),
                    workspace=workspace,
                ),
            )
    return found


__all__ = ["HEALTH_TABLES", "SOURCE_TABLES", "health", "run_health"]
