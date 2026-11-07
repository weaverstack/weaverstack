"""The inert runtime topology: nodes, dependency edges and selection order."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cached_property
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping

from ..graph import Graph
from .result import RunError

if TYPE_CHECKING:
    from ..fabric.resources import Item


@dataclass(frozen=True)
class RunNode:
    """Installed runtime work or a barrier between units of work."""

    node_id: str
    physical_target: object
    primitive_kind: str
    logical_id: object | None = None
    physical_object: object | None = None
    primitive_id: object | None = None
    primitive_object: object | None = None
    role: str | None = None
    #: Opaque to the Runner; only dispatch interprets the installed description.
    installed: object | None = None
    #: A publication barrier only: the Warehouse table it waits on, the consuming
    #: shortcut paths, and the load node that publishes what it waits for.
    publication_of: object | None = None
    publication_targets: tuple[object, ...] = ()
    produced_by: str | None = None
    bound_item: Item | None = None
    #: A refresh barrier only: the ``(schema, table)`` pairs it syncs, or
    #: ``None`` for every table.
    refresh_tables: tuple[tuple[str, str], ...] | None = ()
    #: A semantic refresh only: every recorded source is read in Direct Lake.
    direct_lake: bool = False
    #: The label of the catalogue that owns this node, when several are joined.
    #: Its place supplies the workspace the node runs in and the catalogue that
    #: records it; ``logical_id`` and ``physical_target`` stay local to it.
    owner: str | None = None

    @property
    def sort_key(self) -> tuple[str, str, str, str, str]:
        """Order ready nodes reproducibly from estate identity, then ``node_id``."""

        return (
            getattr(self.physical_target, "kind", ""),
            getattr(self.physical_target, "name", str(self.physical_target)),
            str(self.logical_id or ""),
            self.primitive_kind,
            self.node_id,
        )


@dataclass(frozen=True)
class RunGraph:
    """The selected runtime graph: nodes, edges and the items selected for."""

    nodes: tuple[RunNode, ...] = ()
    edges: tuple[tuple[str, str], ...] = ()
    #: The logical items this graph was selected for.
    items: tuple = ()
    messages: tuple = ()
    #: The catalogues a joined graph spans, in the order given. Their nodes are
    #: ordered in that order where the dependencies leave a choice.
    owners: tuple[str, ...] = ()

    def _key(self, node_id: str):
        node = self.by_id[node_id]
        rank = (
            self.owners.index(node.owner)
            if node.owner in self.owners
            else len(self.owners)
        )
        return (rank, node.sort_key)

    @cached_property
    def by_id(self) -> Mapping[str, RunNode]:
        return MappingProxyType({node.node_id: node for node in self.nodes})

    @cached_property
    def topology(self) -> Graph:
        """The dispatch graph. An edge that closes a cycle is left out, so its
        consumer reads what its producer last left."""

        return Graph((node.node_id for node in self.nodes), self.edges).acyclic(
            key=self._key
        )

    def upstream(self, node_id: str) -> frozenset[str]:
        return frozenset(self.topology.upstream_of(node_id))

    def descendants(self, node_id: str) -> frozenset[str]:
        return frozenset(self.topology.descendants(node_id))

    def order(self) -> tuple[RunNode, ...]:
        """Return a deterministic topological order."""

        found = self.by_id
        return tuple(found[node_id] for node_id in self.topology.order(key=self._key))


def graph_for(request, state) -> RunGraph:
    """Build the graph selected by a request against the observed estate."""

    from .runner import LOAD, TEST

    if request.kind == LOAD:
        return _load_graph(request, state)
    if request.kind == TEST:
        return _test_graph(request, state)
    raise RunError(f"Cannot plan a {request.kind!r} run: no selection rule exists")


def _load_graph(request, state) -> RunGraph:
    from ..joined_dag import local, owner_of
    from ..load_plan import load_dag

    dag = load_dag(
        state.installed,
        items=request.items,
        selection=request.selected,
        names=request.names,
        ancestors=request.ancestors,
        descendants=request.descendants,
    )
    return RunGraph(
        nodes=tuple(
            RunNode(
                node_id=node.node_id,
                physical_target=local(node.physical_target),
                primitive_kind=node.primitive_kind,
                logical_id=local(node.logical_id),
                physical_object=node.physical_object,
                primitive_id=local(node.primitive_id),
                primitive_object=node.primitive_object,
                publication_of=local(node.publication_of),
                publication_targets=tuple(
                    replace(
                        each,
                        target=local(each.target),
                        owner=owner_of(each.target),
                    )
                    for each in node.publication_targets
                ),
                produced_by=node.produced_by,
                bound_item=node.bound_item,
                refresh_tables=node.refresh_tables,
                direct_lake=node.direct_lake,
                role="load",
                owner=node.owner,
            )
            for node in dag.nodes
        ),
        edges=dag.edges,
        items=dag.items,
        messages=dag.messages,
        owners=tuple(place.label for place in state.places),
    )


def _test_graph(request, state) -> RunGraph:
    from ..catalogues import qualify
    from ..errors import ValidationError
    from ..installed import refuse_uncertified_models
    from ..joined_dag import Owned, local, owner_of
    from ..selection import matching, name_patterns
    from ..test_execution import primitive_kind
    from ..test_plan import ValidationEstate, validation_order

    # Each catalogue's validations are matched in their own namespace.
    owners = (
        [None]
        if not state.places
        else [
            place.label
            for place in state.places
            if any(owner_of(item) == place.label for item in request.items)
        ]
    )
    candidates = []
    for owner in owners:
        dag = state.catalogue_for(owner).dag()
        items = tuple(local(item) for item in request.items if owner_of(item) == owner)
        refuse_uncertified_models(dag, items, operation="Test", error=ValidationError)
        candidates.extend(
            (owner, each) for each in ValidationEstate.of(dag).for_items(items)
        )
    patterns = name_patterns(request.names, error=ValidationError)
    if patterns:
        known = ", ".join(sorted(each.qualified for _, each in candidates)) or "none"
        candidates = matching(
            patterns,
            candidates,
            name=lambda pair: pair[1].qualified,
            unmatched=lambda text: ValidationError(
                f"no installed validation in the requested items matches '{text}'. "
                f"Installed: {known}"
            ),
        )
    if request.selected is not None:
        chosen = frozenset(request.selected)
        candidates = [
            (owner, each)
            for owner, each in candidates
            if (each.logical if owner is None else Owned(owner, each.logical)) in chosen
        ]
    nodes = [
        RunNode(
            node_id=(
                str(validation.logical)
                if owner is None
                else qualify(owner, str(validation.logical))
            ),
            physical_target=validation.target,
            primitive_kind=primitive_kind(validation),
            logical_id=validation.logical,
            primitive_id=validation.artefact,
            role=validation.kind,
            installed=validation,
            owner=owner,
        )
        for owner in owners
        for validation in validation_order(
            [each for found, each in candidates if found == owner]
        )
    ]
    return RunGraph(
        nodes=tuple(nodes),
        # Validations are independent of one another by construction: each reads
        # the estate and reports, and none produces what another consumes. An
        # ordering exists for reporting, not for readiness.
        edges=(),
        items=tuple(request.items),
        owners=tuple(place.label for place in state.places),
    )


__all__ = ["RunGraph", "RunNode", "graph_for"]
