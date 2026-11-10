"""The SQL-column observation action in Build's catalogue barrier."""

import json
from dataclasses import replace

from .dependencies import action_key, endpoint_object_key
from .models import BuildBatch, InstallAction
from .payloads import sha256_hex
from .stages import CATALOGUE, PlannedStage


def column_types_stage(items, *, catalogue_target, regenerate=False, endpoints=None):
    filename = "column-types.column-types.json"
    content = json.dumps(
        {"items": sorted(map(str, items)), "regenerate": regenerate}
    ).encode()
    action = InstallAction(
        id="collect-column-types",
        kind="collect_column_types",
        executor="column_types",
        resource_node_id=None,
        payload=filename,
        payload_sha256=sha256_hex(content),
    )
    endpoints = endpoints or {}
    payloads = {filename: content}
    actions = (action,)
    requires = {}
    if endpoints:
        visible = "await-column-endpoint-objects"
        ready_file = "column-types.endpoint-objects.json"
        ready = json.dumps(
            {
                "objects": sorted(
                    {
                        (database, identity.object_id.schema, identity.object_id.object)
                        for identity, database in endpoints.items()
                    }
                )
            }
        ).encode()
        payloads[ready_file] = ready
        actions = (
            InstallAction(
                id=visible,
                kind="await_endpoint_objects",
                executor="await_endpoint_objects",
                resource_node_id=None,
                payload=ready_file,
                payload_sha256=sha256_hex(ready),
            ),
            action,
        )
        requires = {
            visible: tuple(endpoint_object_key(identity) for identity in endpoints),
            action.id: (action_key(visible),),
        }
    return PlannedStage(
        phase=CATALOGUE,
        index=3,
        slug="column-types",
        description="Read installed SQL column types",
        payloads=payloads,
        requires=requires,
        batches=(
            BuildBatch(
                id="column-types", target_id=catalogue_target.id, actions=actions
            ),
        ),
    )


def preserve_rebuilt_column_inventory(stages, catalogue):
    """Carry retained observations in the ordinary table's CREATE action.

    Restoration includes unrelated owners and copied Mirror rows, and cannot be
    blocked by a later failed endpoint observation. Removed claims stay removed.
    """
    from ..catalogue.builtin import BUILTIN_ITEM
    from ..catalogue.render import InstallationScope, render_merge
    from ..catalogue.tables import COLUMN_DATA_TYPE

    def rebuilding(action):
        return (
            action.kind == "build_table"
            and action.resource_node_id == f"{BUILTIN_ITEM}/_.ColumnDataType"
        )

    stages = tuple(stages)
    if not any(
        rebuilding(action)
        for stage in stages
        for batch in stage.batches
        for action in batch.actions
    ):
        return stages
    restores = []
    for item, tables in catalogue.rows.items():
        rows = tables.get(COLUMN_DATA_TYPE.name, ())
        if rows:
            restores.append(
                render_merge(
                    COLUMN_DATA_TYPE,
                    rows,
                    scope=InstallationScope(item.item_type, item.item_name),
                )
            )
    if not restores:
        return stages
    result = []
    for stage in stages:
        payloads = dict(stage.payloads)
        batches = []
        for batch in stage.batches:
            actions = []
            for action in batch.actions:
                if rebuilding(action):
                    assert action.executor == "tsql" and action.payload is not None
                    content = (
                        payloads[action.payload] + ("\n" + "\n".join(restores)).encode()
                    )
                    payloads[action.payload] = content
                    action = replace(action, payload_sha256=sha256_hex(content))
                actions.append(action)
            batches.append(replace(batch, actions=tuple(actions)))
        result.append(replace(stage, payloads=payloads, batches=tuple(batches)))
    return tuple(result)
