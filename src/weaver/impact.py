"""What a failure reaches across the catalogues read together.

Each object downstream of a failed load is classed by how it reads:

* ``behind``: it materialises rows, so it holds the last good copy until it loads.
* ``live``: a View, a shortcut, or a Direct Lake or DirectQuery model table, which
  shows the source as it is now.
* ``frozen``: an Import model table, which holds what its last refresh read.

A Report follows its model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from .catalogue.tables import ERROR, FAILED, ROLE_DATA, ROLE_SHORTCUT
from .catalogues import CatalogueSet, qualify, split

BEHIND = "behind"
LIVE = "live"
FROZEN = "frozen"
FOLLOWS = "follows its model"

#: Load results that make an object the start of an impact.
_BROKEN = (FAILED, ERROR)
#: Model storage modes that read their source at query time.
_LIVE_MODES = ("directlake", "directquery", "dual")


@dataclass(frozen=True)
class AffectedTable:
    name: str
    effect: str

    def to_mapping(self) -> dict:
        return {"name": self.name, "effect": self.effect}


@dataclass(frozen=True)
class Affected:
    catalogue: str
    object_id: str
    kind: str
    effect: str
    tables: tuple[AffectedTable, ...] = ()

    def to_mapping(self) -> dict:
        return {
            "catalogue": self.catalogue,
            "object_id": self.object_id,
            "kind": self.kind,
            "effect": self.effect,
            "tables": [table.to_mapping() for table in self.tables],
        }


@dataclass(frozen=True)
class Impact:
    """One failed object and everything downstream of it."""

    catalogue: str
    object_id: str
    status: str
    completed_at: datetime | None
    affected: tuple[Affected, ...] = ()

    def to_mapping(self) -> dict:
        return {
            "catalogue": self.catalogue,
            "object_id": self.object_id,
            "status": self.status,
            "completed_at": None
            if self.completed_at is None
            else self.completed_at.isoformat(),
            "affected": [each.to_mapping() for each in self.affected],
        }


def impacts(joined: CatalogueSet, statuses: Mapping[str, object]) -> tuple[Impact, ...]:
    """Each failed object's reach, across every catalogue in ``joined``.

    ``statuses`` maps a qualified node to its effective ``RuntimeStatus``.
    """

    found = []
    for qualified, status in sorted(statuses.items()):
        if status is None or status.result not in _BROKEN:
            continue
        if qualified not in joined.graph:
            continue
        label, node_id = split(qualified)
        found.append(
            Impact(
                catalogue=label,
                object_id=node_id,
                status=status.result,
                completed_at=status.completed_at,
                affected=reach(joined, (qualified,)),
            )
        )
    return tuple(found)


def reach(joined: CatalogueSet, roots) -> tuple[Affected, ...]:
    """Everything downstream of ``roots``, classed by how it reads."""

    reached: set[str] = set()
    for root in roots:
        reached.update(joined.graph.descendants(root))
    reached.difference_update(roots)
    upstream = reached | set(roots)
    found = []
    for qualified in joined.graph.order():
        if qualified not in reached:
            continue
        member, node = joined.locate(qualified)
        affected = _classed(joined, member, node, upstream)
        if affected is not None:
            found.append(affected)
    return tuple(found)


def _classed(joined, member, node, upstream) -> Affected | None:
    object_type = (node.object_type or "").casefold()
    if object_type == "semantic_model":
        tables = _model_tables(member, node, upstream)
        effect = LIVE if any(t.effect == LIVE for t in tables) else FROZEN
        return Affected(member.label, node.node_id, "semantic model", effect, tables)
    if object_type == "report":
        return Affected(member.label, node.node_id, "report", FOLLOWS)
    if node.role == ROLE_SHORTCUT:
        return Affected(member.label, node.node_id, "shortcut", LIVE)
    if node.role != ROLE_DATA:
        return None
    if object_type == "view":
        return Affected(member.label, node.node_id, "view", LIVE)
    return Affected(member.label, node.node_id, object_type or "table", BEHIND)


def _model_tables(member, node, upstream) -> tuple[AffectedTable, ...]:
    tables = {}
    for edge in member.dag.reads(node.identity):
        if edge.semantic_table is None:
            continue
        if qualify(member.label, str(edge.upstream)) not in upstream:
            continue
        mode = (edge.source_mode or "").casefold()
        tables[edge.semantic_table] = LIVE if mode in _LIVE_MODES else FROZEN
    return tuple(AffectedTable(name, effect) for name, effect in sorted(tables.items()))


__all__ = [
    "BEHIND",
    "FOLLOWS",
    "FROZEN",
    "LIVE",
    "Affected",
    "AffectedTable",
    "Impact",
    "impacts",
    "reach",
]
