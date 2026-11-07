"""Installed catalogue state for run planning."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from types import MappingProxyType
from typing import Mapping

from ..catalogue.state import Catalogue
from .result import RunError


@dataclass(frozen=True)
class RunPlace:
    """One catalogue of a run across several: its label, the Workspace its
    objects run in, and the catalogue that records them."""

    label: str
    workspace: object
    catalogue: Catalogue

    @property
    def catalogue_name(self) -> str:
        return str(self.workspace.catalogue).rpartition("/")[2]

    @property
    def reference(self) -> str:
        return f"{self.workspace.workspace}/Warehouse/{self.catalogue_name}"


@dataclass(frozen=True)
class RunState:
    """The catalogue snapshot read once for a Runner.

    A run across several catalogues has a place for each, in the order given,
    and ``catalogue`` is the first place's. Each node is recorded in the
    catalogue of the place that owns it.
    """

    catalogue: Catalogue
    places: tuple[RunPlace, ...] = ()

    @classmethod
    def joined(cls, places) -> "RunState":
        places = tuple(places)
        return cls(catalogue=places[0].catalogue, places=places)

    @cached_property
    def by_label(self) -> Mapping[str, RunPlace]:
        return MappingProxyType({place.label: place for place in self.places})

    def place(self, owner: str | None) -> RunPlace | None:
        """The place that owns a node, or ``None`` for a single-catalogue run."""

        return None if owner is None else self.by_label[owner]

    def workspace_for(self, owner: str | None, default=None):
        place = self.place(owner)
        return default if place is None else place.workspace

    def catalogue_for(self, owner: str | None) -> Catalogue:
        place = self.place(owner)
        return self.catalogue if place is None else place.catalogue

    @cached_property
    def installed(self):
        """The installed graph the run plans on: one catalogue's, or all of
        them joined."""

        if not self.places:
            return self.catalogue.dag()
        from ..catalogues import Member, join
        from ..joined_dag import JoinedDag

        return JoinedDag(
            join(
                [
                    Member(
                        label=place.label,
                        workspace=place.workspace.workspace,
                        catalogue_name=place.catalogue_name,
                        catalogue=place.catalogue,
                        dag=place.catalogue.dag(),
                    )
                    for place in self.places
                ]
            )
        )

    def to_mapping(self) -> dict:
        return {
            "format_version": 1,
            "catalogue": self.catalogue.to_mapping(),
        }

    @classmethod
    def from_mapping(cls, mapping) -> "RunState":
        version = mapping.get("format_version")
        if version != 1:
            raise RunError(
                f"Run state version {version!r} is unsupported; this Weaver version "
                "supports version 1. Recreate the run state with this Weaver version."
            )
        return cls(catalogue=Catalogue.from_mapping(mapping["catalogue"]))


def read_installed_catalogue(*, session, workspace=None, tables=None) -> Catalogue:
    """Read the installed catalogue used for planning and recording.

    ``tables`` widens the default read without adding another round trip.
    """

    from ..catalogue.state import READABLE_TABLES, catalogue_for

    workspace = workspace if workspace is not None else session.workspace
    if workspace is None or not workspace.catalogue:
        raise RunError(
            "This run needs a Workspace with a Weaver catalogue. Pass a Workspace "
            "that names its catalogue Warehouse."
        )
    return catalogue_for(
        session, workspace, tables=READABLE_TABLES if tables is None else tuple(tables)
    )


__all__ = ["RunPlace", "RunState", "read_installed_catalogue"]
