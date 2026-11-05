"""Resolve and read the catalogues an operation was given together.

The working workspace resolves exactly as it does for one catalogue. The
catalogues given supply context; their order decides only presentation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from ..declaration.model import WeaverItemId
from ..errors import CommandError
from ..workspaces import CatalogueRef, EnvironmentRef, Workspace
from .items import requested_items
from .workspace import operation_workspace


@dataclass(frozen=True)
class Place:
    """One catalogue given: its label and the Workspace an operation uses there."""

    label: str
    workspace: Workspace
    catalogue_name: str

    @property
    def reference(self) -> str:
        return f"{self.workspace.workspace}/Warehouse/{self.catalogue_name}"


def is_joined(catalogue) -> bool:
    """Whether ``catalogue`` names more than one catalogue."""

    return not isinstance(catalogue, (str, type(None))) and len(tuple(catalogue)) > 1


def resolve_places(
    operation: str,
    catalogues: Sequence[str],
    *,
    workspace=None,
    workspace_config=None,
    environment=None,
    session=None,
) -> tuple[Workspace, tuple[Place, ...]]:
    """The working Workspace and one Place per catalogue, in the order given.

    The working workspace resolves by the ordinary precedence. Only when nothing
    names one does the first catalogue's workspace stand in. A catalogue
    without a workspace is in the working one.

    Every Place uses the working Environment, qualified by its workspace, so
    work in another team's workspace runs the same Weaver and needs none of its
    configuration.
    """

    from ..catalogues import labels_for

    references = [CatalogueRef.parse(each) for each in catalogues]
    home = _working_workspace(
        operation,
        references,
        workspace=workspace,
        workspace_config=workspace_config,
        environment=environment,
        session=session,
    )
    owners = [
        (reference.owner(home.workspace), reference.name) for reference in references
    ]
    if len({(w.casefold(), c.casefold()) for w, c in owners}) != len(owners):
        raise CommandError(f"{operation} was given the same catalogue more than once")
    places = tuple(
        Place(label=label, catalogue_name=name, workspace=place_workspace(home, owner, name))
        for label, (owner, name) in zip(labels_for(owners), owners)
    )
    return home, places


def place_workspace(home: Workspace, owner: str, catalogue_name: str) -> Workspace:
    """The Workspace an operation uses in ``owner`` with that catalogue.

    The working workspace keeps its own configuration. Another keeps only the
    working Environment and execution settings.
    """

    if owner.casefold() == home.workspace.casefold():
        return replace(home, workspace=owner, catalogue=f"Warehouse/{catalogue_name}")
    return replace(
        home,
        workspace=owner,
        catalogue=f"Warehouse/{catalogue_name}",
        environment=(
            None
            if home.environment is None
            else EnvironmentRef(
                workspace=home.environment.owner(home.workspace),
                name=home.environment.name,
            )
        ),
        targets={},
        mirror=None,
    )


def _working_workspace(
    operation, references, *, workspace, workspace_config, environment, session
) -> Workspace:
    from ..config import discovered_workspace_config
    from ..workflow import _inherited

    def resolve(name):
        return operation_workspace(
            operation,
            workspace=name,
            workspace_config=workspace_config,
            environment=environment,
            session=session,
            needs_catalogue=False,
        )

    named = (
        workspace is not None
        or workspace_config is not None
        or _inherited(session) is not None
        or discovered_workspace_config() is not None
    )
    if named:
        return resolve(workspace)
    try:
        return resolve(None)
    except CommandError:
        first = next((each.workspace for each in references if each.workspace), None)
        if first is None:
            raise
        return resolve(first)


def home_places(places: Sequence[Place], home: Workspace) -> tuple[Place, ...]:
    """The catalogues given in the working workspace, its own catalogue first."""

    local = [
        place
        for place in places
        if place.workspace.workspace.casefold() == home.workspace.casefold()
    ]
    own = (home.catalogue or "").rpartition("/")[2].casefold()
    return tuple(sorted(local, key=lambda place: place.catalogue_name.casefold() != own))


def requested_by_label(
    operation: str, items, places: Sequence[Place], home: Workspace
) -> dict[str, tuple[WeaverItemId, ...]]:
    """Each catalogue's requested items. An empty tuple means all of them.

    ``Kind/Name`` is an item of the working workspace's catalogue,
    ``Workspace/Kind/Name`` one in another's, and a bare label or workspace name
    every item of that catalogue. The result keeps the order the catalogues were
    given.
    """

    def matching(owner: str) -> list[Place]:
        return [
            place
            for place in places
            if place.label.casefold() == owner.casefold()
            or place.workspace.workspace.casefold() == owner.casefold()
        ]

    values = (items,) if isinstance(items, str) else tuple(items)
    found: dict[str, list[WeaverItemId]] = {}
    whole: set[str] = set()
    for value in values:
        text = str(value).strip().strip("/")
        parts = text.split("/")
        if len(parts) == 1 or (len(parts) == 2 and matching(text)):
            owner, local = text, None
        elif len(parts) == 3:
            owner, local = parts[0], "/".join(parts[1:])
        else:
            owner, local = home.workspace, text
        candidates = (
            list(home_places(places, home))[:1]
            if local is not None and owner == home.workspace
            else matching(owner)
        )
        if len(candidates) != 1:
            raise CommandError(
                f"{value} names {owner}, which is "
                f"{'none' if not candidates else 'more than one'} of the catalogues "
                f"given to {operation}"
            )
        label = candidates[0].label
        if local is None:
            whole.add(label)
            found.setdefault(label, [])
        else:
            found.setdefault(label, []).extend(requested_items(local, what=operation))
    return {
        place.label: (
            () if place.label in whole else tuple(dict.fromkeys(found[place.label]))
        )
        for place in places
        if place.label in found
    }


#: Catalogues read at once. Each read holds one TDS connection.
READERS = 8


def concurrently(entries, work) -> list:
    """``work`` over each entry, in order: each result or the exception it raised."""

    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context

    def guarded(entry):
        try:
            return work(entry)
        except Exception as exc:  # noqa: BLE001 - reported per catalogue
            return exc

    if not entries:
        return []
    with ThreadPoolExecutor(max_workers=min(READERS, len(entries))) as pool:
        futures = [pool.submit(copy_context().run, guarded, e) for e in entries]
        return [future.result() for future in futures]


def retried(work):
    """Once more after a pause: a Warehouse can refuse a connection while busy."""

    import time

    try:
        return work()
    except Exception:  # noqa: BLE001 - the second attempt's error is reported
        time.sleep(5)
        return work()


__all__ = [
    "Place",
    "concurrently",
    "home_places",
    "is_joined",
    "place_workspace",
    "requested_by_label",
    "resolve_places",
    "retried",
]
