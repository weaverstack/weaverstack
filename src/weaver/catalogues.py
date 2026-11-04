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

    def to_mapping(self) -> dict:
        return {
            "consumer": self.consumer,
            "target": self.target,
            "producer": self.producer,
            "reason": self.reason,
        }


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

    def across(self, member: Member, statuses) -> "Across":
        """What Health needs about ``member``'s nodes from the other catalogues.

        ``statuses`` maps a qualified node to its effective load status.
        """

        return Across(self, member, statuses)


class Across:
    """Ancestry beyond one catalogue, for that catalogue's Health."""

    def __init__(self, joined: CatalogueSet, member: Member, statuses) -> None:
        self._joined = joined
        self._member = member
        self._statuses = statuses
        crossed = set()
        for crossing in joined.crossings:
            if crossing.producer is None or crossing.consumer not in joined.graph:
                continue
            crossed.add(crossing.consumer)
            crossed.update(joined.graph.descendants(crossing.consumer))
        self._crossed = frozenset(crossed)

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
        from .health import established, participates_in_load_state

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
            if each in local:
                continue
            _owner, other = self._joined.locate(each)
            if not participates_in_load_state(other):
                continue
            status = self._statuses.get(each)
            found.append(
                ForeignAncestor(
                    name=self._joined.display(each),
                    established_at=established(status),
                    result=PENDING if status is None else status.result,
                    in_cycle=each in cycle,
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


def join(
    members: Sequence[Member], *, report_models: Mapping[str, str] | None = None
) -> CatalogueSet:
    """Join catalogues where a physical shortcut lands on another's object.

    ``report_models`` maps a qualified Report node to the GUID of the semantic
    model Power BI binds it to. A Report bound to a model another catalogue
    installs joins that model, as a thin Report on a central model does.
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
            crossings.extend(_crossings(member, shortcut, installed))
    crossings.extend(_report_crossings(members, report_models or {}))

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


def _report_crossings(members, report_models: Mapping[str, str]):
    from .installed import SEMANTIC_MODEL

    models = {}
    for member in members:
        for item in member.dag.installations:
            if item.item_type != SEMANTIC_MODEL:
                continue
            row = next(
                iter(member.catalogue.rows.get(item, {}).get(INSTALLATION.name, ())),
                {},
            )
            if row.get("item_id"):
                models[str(row["item_id"]).casefold()] = qualify(
                    member.label, str(WeaverDocumentId.model_root(item))
                )
    found = []
    for report, model in sorted(report_models.items()):
        producer = models.get(str(model).casefold())
        found.append(
            Crossing(
                report,
                f"SemanticModel {model}",
                producer=producer,
                reason=None
                if producer
                else f"No catalogue given installs the semantic model {model}.",
            )
        )
    return found


def _crossings(member: Member, shortcut: "InstalledShortcut", installed):
    from .installed import stored_identity

    workspace = shortcut.target_workspace or member.workspace
    item = shortcut.target_item
    path = shortcut.target_schema + (
        f".{shortcut.target_object}" if shortcut.target_object else ""
    )
    target = f"{workspace}/{item}/{path}"
    consumer = qualify(member.label, str(shortcut.destination))
    found = installed.get(
        (workspace.casefold(), item.item_type.casefold(), item.item_name.casefold()), []
    )
    if not found:
        return (
            Crossing(
                consumer,
                target,
                reason=f"No catalogue given installs {workspace}/{item}.",
            ),
        )
    if len(found) > 1:
        names = ", ".join(sorted(producer.label for producer, _ in found))
        return (
            Crossing(
                consumer,
                target,
                reason=f"{workspace}/{item} is installed by more than one catalogue given: {names}.",
            ),
        )
    producer, logical = found[0]
    by_id = producer.dag.by_id

    if shortcut.shortcut_type == SCHEMA_SHORTCUT:
        destination_schema = shortcut.destination.schema
        reached = []
        for node in producer.dag.nodes:
            identity = node.identity
            if (
                node.item != logical
                or not isinstance(identity, WeaverDocumentId)
                or identity.is_files
                or identity.object_id.schema.casefold()
                != shortcut.target_schema.casefold()
            ):
                continue
            destination = WeaverDocumentId(
                shortcut.destination.item,
                ObjectId(destination_schema, identity.object_id.object),
            )
            if str(destination) in member.dag.by_id:
                reached.append(
                    Crossing(
                        qualify(member.label, str(destination)),
                        target,
                        producer=qualify(producer.label, node.node_id),
                    )
                )
        return tuple(reached)

    if shortcut.shortcut_type == FOLDER_SHORTCUT:
        parts = shortcut.target_schema.strip("/").split("/")
        if len(parts) != 2:
            return (
                Crossing(
                    consumer,
                    target,
                    reason="Only a Schema/Folder path names one installed folder.",
                ),
            )
        identity = stored_identity(logical, f"Files/{parts[0]}", parts[1])
    else:
        identity = stored_identity(
            logical, shortcut.target_schema, shortcut.target_object or ""
        )
    if str(identity) not in by_id:
        return (
            Crossing(
                consumer,
                target,
                reason=f"{identity} is not installed in {producer.label}.",
            ),
        )
    return (
        Crossing(consumer, target, producer=qualify(producer.label, str(identity))),
    )


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
