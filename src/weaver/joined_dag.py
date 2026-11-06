"""Several catalogues' installed graphs, presented as one for load planning.

Each catalogue keeps its own logical namespace. Composing them qualifies every
identity, item and target by the catalogue's label (:class:`Owned`), so two
teams' ``Warehouse/Mart`` stay distinct, and the local identity is always
recoverable for recording in the catalogue that owns it. A physical shortcut
that lands on another catalogue's object reads that object, as a logical
shortcut reads its source.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cached_property
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

from .catalogues import SEPARATOR, qualify, split
from .targets import PhysicalTargetRef

if TYPE_CHECKING:
    from .catalogues import CatalogueSet
    from .installed import InstalledNode


@dataclass(frozen=True)
class Owned:
    """A catalogue-local value, qualified by the label of the catalogue owning it."""

    owner: str
    value: Any

    def __str__(self) -> str:
        return qualify(self.owner, str(self.value))

    def __lt__(self, other) -> bool:
        return str(self) < str(other)

    @property
    def item(self) -> "Owned":
        return Owned(self.owner, self.value.item)

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self.value, name)


@dataclass(frozen=True)
class OwnedTarget(PhysicalTargetRef):
    """A physical target in the workspace of the catalogue named ``owner``."""

    owner: str = ""

    @property
    def local(self) -> PhysicalTargetRef:
        return PhysicalTargetRef(kind=self.kind, name=self.name)


def owner_of(value) -> str | None:
    """The catalogue label a composed value carries, or ``None`` for a local one."""

    return getattr(value, "owner", None) or None


def local(value):
    """The catalogue-local form of a composed value."""

    if isinstance(value, Owned):
        return value.value
    if isinstance(value, OwnedTarget):
        return value.local
    return value


def parse_owned(text: str, parse):
    """``parse`` a value, keeping a ``Label::`` qualification as :class:`Owned`."""

    label, separator, rest = str(text).partition(SEPARATOR)
    return Owned(label, parse(rest)) if separator else parse(text)


class OwnedNode:
    """An installed node as the composed graph presents it."""

    __slots__ = ("owner", "inner")

    def __init__(self, owner: str, inner: "InstalledNode") -> None:
        self.owner = owner
        self.inner = inner

    @property
    def node_id(self) -> str:
        return qualify(self.owner, self.inner.node_id)

    @property
    def identity(self) -> Owned:
        return Owned(self.owner, self.inner.identity)

    @property
    def item(self) -> Owned:
        return Owned(self.owner, self.inner.item)

    @property
    def target(self) -> OwnedTarget:
        return OwnedTarget(self.inner.target.kind, self.inner.target.name, self.owner)

    def __getattr__(self, name: str):
        return getattr(self.inner, name)

    def __eq__(self, other) -> bool:
        return isinstance(other, OwnedNode) and other.node_id == self.node_id

    def __hash__(self) -> int:
        return hash(self.node_id)

    def __repr__(self) -> str:
        return f"OwnedNode({self.node_id!r})"


class JoinedDag:
    """The installed graphs of a :class:`weaver.catalogues.CatalogueSet` as one.

    It answers what load planning asks of an
    :class:`weaver.installed.InstalledDag`, over qualified identities.
    """

    def __init__(self, joined: "CatalogueSet") -> None:
        self.joined = joined
        self.graph = joined.graph

    @cached_property
    def by_id(self) -> Mapping[str, OwnedNode]:
        return MappingProxyType(
            {
                qualify(member.label, node.node_id): OwnedNode(member.label, node)
                for member in self.joined.members
                for node in member.dag.nodes
            }
        )

    @property
    def nodes(self) -> tuple[OwnedNode, ...]:
        return tuple(self.by_id.values())

    def node(self, identity) -> OwnedNode:
        owner, value = identity.owner, identity.value
        return OwnedNode(owner, self._member(owner).dag.node(value))

    def __contains__(self, identity) -> bool:
        return str(identity) in self.by_id

    def _member(self, owner: str):
        return self.joined.by_label[owner]

    @cached_property
    def installations(self) -> Mapping[Owned, OwnedTarget]:
        return MappingProxyType(
            {
                Owned(member.label, item): OwnedTarget(
                    target.kind, target.name, member.label
                )
                for member in self.joined.members
                for item, target in member.dag.installations.items()
            }
        )

    @cached_property
    def ambiguous(self) -> Mapping[OwnedTarget, tuple[str, ...]]:
        return MappingProxyType(
            {
                OwnedTarget(target.kind, target.name, member.label): found
                for member in self.joined.members
                for target, found in member.dag.ambiguous.items()
            }
        )

    @cached_property
    def external_references(self) -> Mapping[Owned, tuple[str, ...]]:
        return MappingProxyType(
            {
                Owned(member.label, identity): found
                for member in self.joined.members
                for identity, found in member.dag.external_references.items()
            }
        )

    def unresolved_for(self, node) -> tuple[str, ...]:
        identity = getattr(node, "identity", node)
        return self._member(identity.owner).dag.unresolved_for(identity.value)

    def reads(self, identity) -> tuple:
        owner = identity.owner
        return tuple(
            replace(
                edge,
                upstream=Owned(owner, edge.upstream),
                downstream=Owned(owner, edge.downstream),
            )
            for edge in self._member(owner).dag.reads(identity.value)
        )

    def is_untraced_model(self, node: OwnedNode) -> bool:
        return self._member(node.owner).dag.is_untraced_model(node.inner)

    def select(self, *, items=None, can_load=None, **filters) -> tuple[OwnedNode, ...]:
        wanted = None if items is None else set(items)
        found = []
        for member in self.joined.members:
            local_items = (
                None
                if wanted is None
                else [item.value for item in wanted if item.owner == member.label]
            )
            if local_items is not None and not local_items:
                continue
            found.extend(
                OwnedNode(member.label, node)
                for node in member.dag.select(
                    items=local_items, can_load=can_load, **filters
                )
            )
        return tuple(found)

    def loadables(self, **filters) -> tuple[OwnedNode, ...]:
        return self.select(can_load=True, **filters)

    def shortcut_sources(self, node: OwnedNode):
        """What a shortcut destination reads, and the readiness each read needs.

        A local logical shortcut reads its source with nothing between. A
        physical shortcut landing on another catalogue's Warehouse table reads
        what OneLake publishes, so the Lakehouse path must see the commit.
        """

        from .load_plan import OneLakeReadiness

        found = [
            (OwnedNode(node.owner, parent), None)
            for parent in self._member(node.owner).dag.parents(node.inner.node_id)
        ]
        for crossing in self._crossings_into.get(node.node_id, ()):
            producer = self.by_id[crossing.producer]
            readiness = None
            if (
                not producer.target.is_lakehouse
                and producer.effective_object_type == "table"
                and node.target.is_lakehouse
            ):
                destination = node.inner.identity
                # A schema shortcut presents the producer's table under its own
                # schema name; a table shortcut names its own table.
                named = getattr(destination, "object_id", None)
                readiness = OneLakeReadiness(
                    target=node.target,
                    schema=destination.schema if named is None else named.schema,
                    object=(
                        producer.inner.identity.object_id.object
                        if named is None
                        else named.object
                    ),
                )
            found.append((producer, readiness))
        return tuple(found)

    @cached_property
    def _crossings_into(self) -> Mapping[str, tuple]:
        found: dict[str, list] = {}
        for crossing in self.joined.crossings:
            if crossing.producer in self.by_id and crossing.consumer in self.by_id:
                found.setdefault(crossing.consumer, []).append(crossing)
        return MappingProxyType({key: tuple(value) for key, value in found.items()})


__all__ = [
    "JoinedDag",
    "Owned",
    "OwnedNode",
    "OwnedTarget",
    "local",
    "owner_of",
    "parse_owned",
    "split",
]
