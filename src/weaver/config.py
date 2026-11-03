"""Read workspace configuration into a :class:`Workspace`."""

from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path
from typing import Any, Mapping

from .declaration.model import WeaverItemId
from .errors import ConfigError, IdentityError
from .workspaces import (
    EnvironmentRef,
    ExecutionSettings,
    TargetDeclaration,
    Workspace,
)

#: The next action when an operation needs a catalogue and none is configured.
CATALOGUE_HINT = (
    "Name its Warehouse with catalogue: in workspace configuration, "
    "--catalogue Warehouse/<name> on the command line, or catalogue= in Python"
)

_KEYS = {
    "workspace",
    "environment",
    "catalogue",
    "mirror",
    "execution",
    "targets",
    "data_sources",
    "catalogue_dashboard",
}

_RETIRED_KEYS = ("lakehouses", "warehouses")


def load_workspace(path: str | Path) -> Workspace:
    import yaml

    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ConfigError(f"Workspace configuration not found: {config_path}")
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return parse_workspace(payload, base_dir=config_path.parent)


def parse_workspace(payload: Any, base_dir: str | Path | None = None) -> Workspace:
    if not isinstance(payload, dict):
        raise ConfigError("Workspace configuration must be a mapping")
    retired = [key for key in _RETIRED_KEYS if key in payload]
    if retired:
        raise ConfigError(
            "Unsupported Workspace configuration keys: "
            + ", ".join(f"{key}:" for key in retired)
            + ". Use one item-keyed targets: mapping, for example "
            "'Lakehouse/Landing: Landing_Dev'."
        )
    unknown = set(payload) - _KEYS
    if unknown:
        raise ConfigError(
            "Workspace configuration has unknown keys: " + ", ".join(sorted(unknown))
        )
    if "workspace" not in payload:
        raise ConfigError("Workspace configuration must define 'workspace'")

    try:
        return Workspace(
            workspace=_text(payload["workspace"], where="workspace"),
            environment=payload.get("environment"),
            catalogue=payload.get("catalogue"),
            mirror=payload.get("mirror"),
            execution=_execution(payload.get("execution"), where="execution"),
            targets=_targets(payload.get("targets")),
            data_sources=payload.get("data_sources", {}),
            catalogue_dashboard=_optional_text(
                payload.get("catalogue_dashboard"), where="catalogue_dashboard"
            ),
        )
    except TypeError as exc:
        raise ConfigError(f"Workspace configuration is incomplete: {exc}") from exc
    except IdentityError as exc:
        # Report invalid names as configuration errors so users know where to fix them.
        raise ConfigError(f"Workspace configuration is invalid: {exc}") from exc


DEFAULT_FILE = "workspace-config.yml"


def discovered_workspace_config(directory: str | Path | None = None) -> Path | None:
    candidate = Path(directory or Path.cwd()) / DEFAULT_FILE
    return candidate if candidate.is_file() else None


def resolve_workspace(
    *,
    workspace: str | None = None,
    environment: EnvironmentRef | str | None = None,
    catalogue: str | None = None,
    workspace_config: str | Path | None = None,
) -> Workspace:
    """Resolve explicit values before the project configuration."""

    if workspace is None and workspace_config is None:
        workspace_config = discovered_workspace_config()
    configured = load_workspace(workspace_config) if workspace_config else None
    resolved_identity = (
        workspace
        if workspace is not None
        else (configured.workspace if configured is not None else None)
    )
    if resolved_identity is None:
        raise ConfigError(
            f"A Workspace is required. Use --workspace or --workspace-config, "
            f"or run from a project directory holding {DEFAULT_FILE}."
        )

    common = {
        "workspace": resolved_identity,
        "environment": environment
        if environment is not None
        else (configured.environment if configured is not None else None),
        "catalogue": catalogue
        if catalogue is not None
        else (configured.catalogue if configured is not None else None),
        "mirror": configured.mirror if configured is not None else None,
        "execution": configured.execution
        if configured is not None
        else ExecutionSettings(),
        "targets": configured.targets if configured is not None else {},
        "data_sources": configured.data_sources if configured is not None else {},
        "catalogue_dashboard": configured.catalogue_dashboard
        if configured is not None
        else None,
    }
    return Workspace(**common)


#: Fields a caller may replace on a resolved Workspace. ``workspace`` is not one:
#: naming another workspace resolves its configuration instead.
OVERRIDABLE = (
    "environment",
    "catalogue",
    "mirror",
    "execution",
    "targets",
    "data_sources",
    "catalogue_dashboard",
)


def with_overrides(workspace: Workspace, overrides: Mapping[str, Any]) -> Workspace:
    """``workspace`` with each given setting changed and every other kept.

    A scalar replaces its value. ``execution`` changes only the concurrency
    settings it names; ``targets`` and ``data_sources`` change only the entries
    they name. Values take the workspace configuration's shapes, or the typed
    values a Workspace holds, and are validated as configuration is. A typed
    ``ExecutionSettings`` is complete, so it replaces the whole value. ``None``
    and an empty mapping change nothing.
    """

    from .semantic_models.expressions import source_mappings

    unknown = set(overrides) - set(OVERRIDABLE)
    if unknown:
        raise ConfigError(
            "Workspace configuration has unknown keys: " + ", ".join(sorted(unknown))
        )
    changes = {name: value for name, value in overrides.items() if value is not None}
    if "execution" in changes and not isinstance(
        changes["execution"], ExecutionSettings
    ):
        changes["execution"] = _execution(
            changes["execution"], where="execution", base=workspace.execution
        )
    if "targets" in changes:
        changes["targets"] = {
            **workspace.targets,
            **_targets(_target_payload(changes["targets"])),
        }
    if "data_sources" in changes:
        changes["data_sources"] = {
            **workspace.data_sources,
            **source_mappings(changes["data_sources"]),
        }
    if "catalogue_dashboard" in changes:
        changes["catalogue_dashboard"] = _text(
            changes["catalogue_dashboard"], where="catalogue_dashboard"
        )
    if not changes:
        return workspace
    try:
        return replace(workspace, **changes)
    except IdentityError as exc:
        raise ConfigError(f"Workspace configuration is invalid: {exc}") from exc


def _target_payload(raw: Any) -> Any:
    """Accept typed target keys and declarations beside the YAML spelling."""

    if not isinstance(raw, Mapping):
        return raw
    return {
        str(item): (
            declaration.physical
            if isinstance(declaration, TargetDeclaration)
            else declaration
        )
        for item, declaration in raw.items()
    }


def _text(value: Any, *, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where} must be a non-empty string, got {value!r}")
    return value


def _optional_text(value: Any, *, where: str) -> str | None:
    return None if value is None else _text(value, where=where)


def _execution(
    raw: Any, *, where: str, base: ExecutionSettings | None = None
) -> ExecutionSettings:
    """Parse ``execution`` over ``base``, the defaults unless given.

    .. code-block:: yaml

        execution:
          build:
            warehouse_concurrency: 2
            spark_concurrency: 4
            onelake_concurrency: 8
            shortcut_concurrency: 2
          run:
            spark_concurrency: 4
            warehouse_concurrency: 4
    """

    base = base if base is not None else ExecutionSettings()
    if raw is None:
        return base
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where} must be a mapping")
    unknown = set(raw) - {"build", "run"}
    if unknown:
        raise ConfigError(f"{where} has unknown keys: " + ", ".join(sorted(unknown)))
    return ExecutionSettings(
        build=_concurrency(raw.get("build"), base.build, where=f"{where}.build"),
        run=_concurrency(raw.get("run"), base.run, where=f"{where}.run"),
    )


def _concurrency(raw: Any, base, *, where: str):
    if raw is None:
        return base
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where} must be a mapping")
    unknown = set(raw) - {field.name for field in fields(base)}
    if unknown:
        raise ConfigError(f"{where} has unknown keys: " + ", ".join(sorted(unknown)))
    return replace(base, **raw)


def _targets(raw: Any) -> dict[WeaverItemId, TargetDeclaration]:
    """Parse Weaver-item keys and their Fabric item names.

    .. code-block:: yaml

        targets:
          Lakehouse/Landing: Landing_Dev
          Warehouse/Curated:
            name: Curated_Dev
    """

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError("targets must be a mapping")
    declarations: dict[WeaverItemId, TargetDeclaration] = {}
    for written, value in raw.items():
        where = f"targets[{written!r}]"
        try:
            item = WeaverItemId.parse(written)
        except (IdentityError, TypeError, ValueError) as exc:
            raise ConfigError(
                f"{where} is not an item identity such as Lakehouse/Landing"
            ) from exc
        if isinstance(value, str):
            physical = _text(value, where=where)
        elif isinstance(value, dict):
            unknown = set(value) - {"name"}
            if unknown:
                raise ConfigError(
                    f"{where} has unknown keys: " + ", ".join(sorted(unknown))
                )
            if "name" not in value:
                raise ConfigError(f"{where} must define 'name'")
            physical = _text(value["name"], where=f"{where}.name")
        else:
            raise ConfigError(f"{where} must be a Fabric item name or mapping")
        declarations[item] = TargetDeclaration(physical)
    return declarations
