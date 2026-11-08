"""Reduce retained Spread CLI output; never calls Fabric.

Pass the directory containing runs3/ and runs/ from the retained experiment.
The JSON output records actual counts and hashes, not a replacement run capture.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


def inspect(root: Path) -> dict:
    run = root / "runs3"
    times = json.loads((run / "times.json").read_text())
    result = {"runtime_revision": "efc046e7cf066daefd27f9268413ae05c3ed64e4",
              "run_date": "2026-11-07", "timing_boundary": "CLI harness wall time",
              "times": times, "files": {}}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result["files"][str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for filename, key in (("01-federated-load.json", "coordinated_load"),
                          ("08-federated-stale.json", "stale_recovery")):
        data = json.loads((run / filename).read_text())
        nodes = data["nodes"]
        objects = [node for node in nodes if node.get("logical_id")]
        result[key] = {
            "catalogues_supplied": len(data["catalogues"]),
            "steps": len(nodes), "statuses": dict(Counter(node["status"] for node in nodes)),
            "object_loads": len(objects),
            "object_owner_catalogues": len({node["catalogue"] for node in objects}),
            "all_node_owner_catalogues": len({node["catalogue"] for node in nodes}),
            "primitive_kinds": dict(Counter(node["primitive_kind"] for node in nodes)),
            "workflow_id": data["workflow_id"],
        }
    impact = json.loads((run / "04-impact-health.json").read_text())
    findings = {}
    for catalogue in impact["catalogues"]:
        for section in catalogue.get("report", {}).get("sections", {}).values():
            for finding in section.get("findings", []):
                if "BRZ.Customer" in finding["message"]:
                    findings[catalogue["label"], finding["object_id"]] = finding
    result["impact"] = {
        "catalogues": len(impact["catalogues"]),
        "catalogue_statuses": dict(Counter(cat["status"] for cat in impact["catalogues"])),
        "downstream_subjects": len(findings),
        "downstream_catalogues": len({cat for cat, obj in findings}),
        "subject_types": dict(Counter(obj.split("/")[0] for cat, obj in findings)),
    }
    final = json.loads((run / "09-final-health.json").read_text())
    result["final_health"] = {
        "catalogue_statuses": dict(Counter(cat["status"] for cat in final["catalogues"])),
        "cycles": final["cycles"],
        "findings": [{"catalogue": cat["label"], **finding}
                     for cat in final["catalogues"]
                     for section in cat.get("report", {}).get("sections", {}).values()
                     for finding in section.get("findings", [])],
    }
    return result


if __name__ == "__main__":
    print(json.dumps(inspect(Path(sys.argv[1])), indent=2))
