"""Several Weaver catalogues read together.

Each team's catalogue records its own items. Where an item's physical shortcut
lands on an object another catalogue installs, the graphs join: the shortcut
names a workspace, an item and a path, the producer's ``_.Installation`` binds
that item to a logical one, and the path gives the object. Nothing is declared
for the join.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping, Sequence

from .catalogue.tables import INSTALLATION
from .declaration.metadata import ObjectId
from .declaration.model import (
    FOLDER_SHORTCUT,
    SCHEMA_SHORTCUT,
    WeaverDocumentId,
    WeaverItemId,
)
from .graph import Graph

if TYPE_CHECKING:
    from .catalogue.state import Catalogue
    from .installed import InstalledDag, InstalledNode, InstalledShortcut

#: Joins a catalogue's label to a node ID. Fabric names cannot contain ``:``.
SEPARATOR = "::"


def qualify(label: str, node_id: str) -> str:
    return f"{label}{SEPARATOR}{node_id}"


def split(qualified: str) -> tuple[str, str]:
    label, _, node_id = qualified.partition(SEPARATOR)
    return label, node_id


@dataclass(frozen=True)
class Member:
    """One catalogue in a set: where it lives and what it records."""

    label: str
    workspace: str
    catalogue_name: str
    catalogue: "Catalogue"
    dag: "InstalledDag"
    #: The catalogue a mirrored member reads its mirrored load state from.
    source: "Catalogue | None" = None

    @property
    def reference(self) -> str:
        return f"{self.workspace}/Warehouse/{self.catalogue_name}"


@dataclass(frozen=True)
class Crossing:
    """A physical shortcut, and the object in another catalogue it lands on.

    ``producer`` is ``None`` when no catalogue in the set installs the target;
    ``reason`` then says why.
    """

    consumer: str
    target: str
    producer: str | None = None
    reason: str | None = None
    #: The workspace the shortcut lands in.
    workspace: str | None = None


@dataclass(frozen=True)
class ForeignAncestor:
    """An ancestor reached through another catalogue, named for a reader.

    ``result`` is its last load result, Pending when none is recorded, and
    ``in_cycle`` says it reads the node it is an ancestor of.
    """

    name: str
    established_at: datetime | None
    result: str
    in_cycle: bool = False
    #: When a build last certified it.
    built_at: datetime | None = None


@dataclass(frozen=True)
class CatalogueSet:
    members: tuple[Member, ...]
    crossings: tuple[Crossing, ...] = ()
    graph: Graph = field(default_factory=lambda: Graph(()))

    @property
    def by_label(self) -> Mapping[str, Member]:
        return MappingProxyType({member.label: member for member in self.members})

    def locate(self, qualified: str) -> tuple[Member, "InstalledNode"]:
        label, node_id = split(qualified)
        member = self.by_label[label]
        return member, member.dag.by_id[node_id]

    def display(self, qualified: str) -> str:
        label, node_id = split(qualified)
        return f"{label}: {node_id}"

    def spanning_cycles(self) -> tuple[tuple[str, ...], ...]:
        """The cycles that pass through more than one catalogue."""

        return tuple(
            members
            for members in self.graph.cycles
            if len({split(each)[0] for each in members}) > 1
        )

    def across(self, member: Member, statuses, unread=(), *, unknown=()) -> "Across":
        """What Health needs about ``member``'s nodes from the other catalogues.

        ``statuses`` maps a qualified node to its effective load status.
        ``unread`` names the workspaces of catalogues given that could not be
        read.
        """

        return Across(self, member, statuses, unread, unknown=unknown)


class Across:
    """Ancestry beyond one catalogue, for that catalogue's Health."""

    def __init__(
        self, joined: CatalogueSet, member: Member, statuses, unread=(), *, unknown=()
    ) -> None:
        self._joined = joined
        self._member = member
        self._statuses = statuses
        #: Members whose load state could not be read: their nodes say nothing.
        self._unknown = frozenset(unknown)
        crossed = set()
        unobserved: dict[str, set[str]] = {}
        unread = {workspace.casefold() for workspace in unread}
        for crossing in joined.crossings:
            if crossing.consumer not in joined.graph:
                continue
            reached = {crossing.consumer, *joined.graph.descendants(crossing.consumer)}
            if crossing.producer is not None:
                crossed.update(reached)
            if (crossing.workspace or "").casefold() in unread and (
                crossing.producer is None or split(crossing.producer)[0] in unknown
            ):
                for each in reached:
                    unobserved.setdefault(each, set()).add(crossing.target)
        self._crossed = frozenset(crossed)
        self._unobserved = unobserved

    def unobserved(self, node: "InstalledNode") -> tuple[str, ...]:
        """What this node reads, directly or not, in a catalogue that could not be
        read."""

        qualified = qualify(self._member.label, node.node_id)
        return tuple(sorted(self._unobserved.get(qualified, ())))

    def cycle(self, node: "InstalledNode") -> frozenset[str]:
        """The node IDs in this catalogue that share a cycle with ``node``."""

        qualified = qualify(self._member.label, node.node_id)
        if qualified not in self._joined.graph:
            return frozenset()
        return frozenset(
            split(each)[1]
            for each in self._joined.graph.component(qualified)
            if split(each)[0] == self._member.label
        )

    def ancestors(self, node: "InstalledNode") -> tuple[ForeignAncestor, ...]:
        """Ancestors reached only through another catalogue."""

        from .catalogue.tables import PENDING
        from .health import _instant, established, participates_in_load_state

        qualified = qualify(self._member.label, node.node_id)
        if qualified not in self._crossed:
            return ()
        graph = self._joined.graph
        cycle = set(graph.component(qualified))
        local = {
            qualify(self._member.label, each.node_id)
            for each in self._member.dag.ancestors(node.identity)
        }
        found = []
        for each in graph.ancestors(qualified):
            if each in local or split(each)[0] in self._unknown:
                continue
            _owner, other = self._joined.locate(each)
            if not participates_in_load_state(other):
                continue
            status = self._statuses.get(each)
            owner, _ = self._joined.locate(each)
            registered = owner.catalogue.registered.get(other.identity)
            found.append(
                ForeignAncestor(
                    name=self._joined.display(each),
                    established_at=established(status),
                    result=PENDING if status is None else status.result,
                    in_cycle=each in cycle,
                    built_at=None
                    if registered is None
                    else _instant(registered.build_datetime),
                )
            )
        return tuple(found)


def labels_for(references: Sequence[tuple[str, str]]) -> tuple[str, ...]:
    """A label per ``(workspace, catalogue)``: the workspace, unless two share it."""

    counts: dict[str, int] = {}
    for workspace, _catalogue in references:
        counts[workspace.casefold()] = counts.get(workspace.casefold(), 0) + 1
    return tuple(
        workspace if counts[workspace.casefold()] == 1 else f"{workspace}/{catalogue}"
        for workspace, catalogue in references
    )


def join(members: Sequence[Member]) -> CatalogueSet:
    """Join catalogues where a physical shortcut lands on another's object.

    A shortcut that cannot be matched is a crossing with a reason, so one
    catalogue's malformed row leaves the others joined.
    """

    installed: dict[tuple[str, str, str], list[tuple[Member, WeaverItemId]]] = {}
    for member in members:
        for item, target in member.dag.installations.items():
            row = next(
                iter(member.catalogue.rows.get(item, {}).get(INSTALLATION.name, ())),
                {},
            )
            workspace = str(row.get("workspace_name") or member.workspace)
            key = (workspace.casefold(), target.kind, target.name.casefold())
            installed.setdefault(key, []).append((member, item))

    crossings: list[Crossing] = []
    for member in members:
        for shortcut in member.dag.shortcuts:
            if shortcut.is_logical or shortcut.target_item is None:
                continue
            try:
                crossings.extend(_crossings(member, shortcut, installed))
            except Exception as exc:  # noqa: BLE001 - one row joins nothing
                crossings.append(
                    Crossing(
                        qualify(member.label, str(shortcut.destination)),
                        str(shortcut.target_item),
                        reason=f"Its target could not be matched: {exc}",
                        workspace=shortcut.target_workspace or member.workspace,
                    )
                )

    nodes: list[str] = []
    edges: list[tuple[str, str]] = []
    for member in members:
        nodes.extend(qualify(member.label, node.node_id) for node in member.dag.nodes)
        edges.extend(
            (
                qualify(member.label, edge.upstream),
                qualify(member.label, edge.downstream),
            )
            for edge in member.dag.graph.edges
        )
    known = set(nodes)
    edges.extend(
        (crossing.producer, crossing.consumer)
        for crossing in crossings
        if crossing.producer in known and crossing.consumer in known
    )
    return CatalogueSet(
        members=tuple(members), crossings=tuple(crossings), graph=Graph(nodes, edges)
    )


def _crossings(member: Member, shortcut: "InstalledShortcut", installed):
    """What one physical shortcut lands on in the catalogues given.

    Several logical items can share one physical item, so the producer is the
    one that installs what the shortcut names.
    """

    workspace = shortcut.target_workspace or member.workspace
    item = shortcut.target_item
    path = shortcut.target_schema + (
        f".{shortcut.target_object}" if shortcut.target_object else ""
    )
    target = f"{workspace}/{item}/{path}"
    consumer = qualify(member.label, str(shortcut.destination))

    def unmatched(reason: str):
        return (Crossing(consumer, target, reason=reason, workspace=workspace),)

    candidates = installed.get(
        (workspace.casefold(), item.item_type.casefold(), item.item_name.casefold()), []
    )
    if not candidates:
        return unmatched(f"No catalogue given installs {workspace}/{item}.")
    if (
        shortcut.shortcut_type == FOLDER_SHORTCUT
        and len(shortcut.target_schema.strip("/").split("/")) != 2
    ):
        return unmatched("Only a Schema/Folder path names one installed folder.")
    reached = {
        (producer.label, logical): _reached(producer, logical, shortcut)
        for producer, logical in candidates
    }
    holding = [key for key, nodes in reached.items() if nodes]
    if len(holding) > 1:
        names = ", ".join(sorted(f"{label}: {logical}" for label, logical in holding))
        return unmatched(
            f"{workspace}/{item}/{path} is installed by more than one item given: "
            f"{names}."
        )
    if not holding:
        labels = ", ".join(sorted({label for label, _ in reached}))
        return unmatched(f"{path} is not installed in {labels}.")
    label = holding[0][0]
    found = []
    for node in reached[holding[0]]:
        if shortcut.shortcut_type == SCHEMA_SHORTCUT:
            destination = qualify(
                member.label,
                str(
                    WeaverDocumentId(
                        shortcut.destination.item,
                        ObjectId(
                            shortcut.destination.schema, node.identity.object_id.object
                        ),
                    )
                ),
            )
            # Tables a schema shortcut presents are not documents of the
            # consumer; its readers read the namespace.
            if split(destination)[1] not in member.dag.by_id:
                destination = consumer
        else:
            destination = consumer
        found.append(
            Crossing(
                destination,
                target,
                producer=qualify(label, node.node_id),
                workspace=workspace,
            )
        )
    return tuple(found)


def _reached(producer: Member, logical: WeaverItemId, shortcut) -> list:
    """The producer's installed objects a shortcut names, under one logical item."""

    from .installed import stored_identity

    if shortcut.shortcut_type == SCHEMA_SHORTCUT:
        return [
            node
            for node in producer.dag.nodes
            if node.item == logical
            and isinstance(node.identity, WeaverDocumentId)
            and not node.identity.is_files
            and node.identity.object_id.schema.casefold()
            == shortcut.target_schema.casefold()
        ]
    if shortcut.shortcut_type == FOLDER_SHORTCUT:
        schema, folder = shortcut.target_schema.strip("/").split("/")
        identity = stored_identity(logical, f"Files/{schema}", folder)
    else:
        identity = stored_identity(
            logical, shortcut.target_schema, shortcut.target_object or ""
        )
    node = producer.dag.by_id.get(str(identity))
    return [] if node is None else [node]


__all__ = [
    "Across",
    "CatalogueSet",
    "Crossing",
    "ForeignAncestor",
    "Member",
    "join",
    "labels_for",
    "qualify",
    "split",
]
