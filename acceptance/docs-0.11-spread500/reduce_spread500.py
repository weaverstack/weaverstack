"""Reduce the retained 500-workspace Spread records; never calls Fabric.

Pass the directory holding ``overnight-dashboard-spread500/``,
``spread500-health-fix-rerun/`` and ``catalogue-result-set-batching/``. The
output records the counts and timings the workspace guide reports, with a
SHA-256 of every source file it read. Large finding lists are left out.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

RUN = "overnight-dashboard-spread500/spread500-reduced.json"
RERUN = "spread500-health-fix-rerun/STATUS.md"
CHECKS = {
    "C": "catalogue-result-set-batching/health500-batch-c/measurement-1.json",
    "D": "catalogue-result-set-batching/health500-batch-d/measurement-1.json",
}
TOP = (
    "run_id",
    "source_sha",
    "runtime_version",
    "timing_boundary",
    "capacity",
    "workspace_count",
    "unique_workspace_ids",
    "status",
    "qualifies_full_scenario",
    "missing_stages",
)
STAGE = ("status", "seconds", "workflow_id", "expected_failure")
RUN_FIELDS = (
    "status",
    "catalogues_supplied",
    "steps",
    "statuses",
    "object_loads",
    "object_owner_catalogues",
    "all_node_owner_catalogues",
    "readiness_steps",
    "primitive_kinds",
    "unexpected_failures_or_pending",
)
HEALTH_FIELDS = (
    "catalogues_supplied",
    "complete",
    "catalogue_statuses",
    "unreadable_catalogues",
    "downstream_subjects_naming_customer",
    "downstream_catalogues_naming_customer",
    "downstream_subject_types",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reduce(root: Path) -> dict:
    run = json.loads((root / RUN).read_text())
    result = {key: run[key] for key in TOP}
    result["stages"] = {}
    for name, stage in run["stages"].items():
        reduced = {key: stage[key] for key in STAGE if key in stage}
        if "run" in stage:
            reduced["run"] = {
                k: stage["run"][k] for k in RUN_FIELDS if k in stage["run"]
            }
        if "health" in stage:
            health = stage["health"]
            reduced["health"] = {k: health[k] for k in HEALTH_FIELDS if k in health}
        result["stages"][name] = reduced

    result["health_checks"] = {}
    for label, relative in CHECKS.items():
        measured = json.loads((root / relative).read_text())
        result["health_checks"][label] = {
            "inventories": measured["inventories"],
            "health_readers": measured["health_readers"],
            "native_seconds": round(measured["native_seconds"], 3),
            "total_session_seconds": round(measured["total_session_seconds"], 3),
            "checks": measured["checks"],
            "status": measured["status"],
        }

    status = (root / RERUN).read_text()
    result["intermediate_rerun"] = {
        "impact_health_failed": "112 readable/388 unreadable" in status,
        "file_descriptors_exhausted": "errno24" in status,
        "only_bronze_reloaded_after_abort": "Wider downstream recovery was not performed"
        in status,
    }
    result["sources"] = {
        relative: _sha(root / relative) for relative in (RUN, RERUN, *CHECKS.values())
    }
    return result


if __name__ == "__main__":
    print(json.dumps(reduce(Path(sys.argv[1])), indent=1, sort_keys=True))
