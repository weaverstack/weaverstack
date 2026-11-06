"""The Catalogue Dashboard over several catalogues assesses Health as
`weaver health` does across them.

Each estate is assessed twice: by :func:`weaver.health.assess_joined`, and by
the renderer under Node over one payload holding every catalogue's rows, each
item and node key qualified by its catalogue's code, as the model's measures
carry them. The findings must agree on catalogue, area, code, severity and
object.
"""

from __future__ import annotations

import json
import subprocess
from datetime import timedelta

import pytest
from support.dashboard_payload import FIELD, ROW, TABLE, page_payload, table
from support.weaver_test import weaver_test
from test_dashboard_health_representation import (
    RENDERER,
    UNOBSERVED,
    _dashboard_rows,
    _node,
)
from test_joined_health_representation import (
    EARLIER,
    LATER,
    NOW,
    _cycle_members,
    alpha_and_beta,
    central,
    members,
    sales,
)

from weaver.catalogue.claims import catalogue_columns
from weaver.health import assess_joined

OWNER = ""
#: The payload columns that name an item or a node, which the measures qualify.
QUALIFIED = {"item", "primaryitem", "sourceitem", "key", "down", "up", "through"}

ASSESS = """
const D = require(process.argv[1]).load();
let text = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { text += chunk; });
process.stdin.on("end", () => {
  const parsed = D.parsePayload(text);
  const m = D.buildModel(parsed.tables, parsed.problems);
  const health = D.assessHealth(m, { asOf: Number(process.argv[2]) });
  const found = health.all.map((f) => [f.area, f.code, f.severity, f.node ? f.node.id : [f.item, f.schema || "", f.object || ""].join("|")]);
  process.stdout.write(JSON.stringify({ findings: found, problems: m.problems }));
});
"""


def _sections(payload: str) -> list[tuple[str, list[str], list[list[str]]]]:
    found = []
    for chunk in payload.split(TABLE)[1:]:
        rows = chunk.split(ROW)
        head = rows[0].split(FIELD)
        found.append((head[0], head[1:], [r.split(FIELD) for r in rows[1:]]))
    return found


def joined_payload(entries) -> str:
    """One page payload over several catalogues, as the measures build it."""

    merged: dict[str, tuple[list[str], list]] = {}
    shortcuts = []
    for code, member in enumerate(entries, start=1):
        rows = _dashboard_rows(member.catalogue)
        for row in rows.get("Installation", []):
            row["workspace_name"] = member.workspace
        for name, columns, values in _sections(page_payload(rows, "health", at=NOW)):
            if name in ("meta", "page"):
                merged.setdefault(name, (columns, values))
                continue
            qualified = [
                [
                    f"{v}{OWNER}{code}" if c in QUALIFIED and v else v
                    for c, v in zip(columns, value)
                ]
                for value in values
            ]
            merged.setdefault(name, (columns, []))[1].extend(qualified)
        for row in rows.get("Shortcut", []):
            if row.get("target_type") not in ("physical", "Physical"):
                continue
            shortcuts.append(
                [
                    f"{row['item_type']}/{row['item_name']}{OWNER}{code}",
                    row["schema_name"],
                    row["object_name"],
                    str(row["shortcut_type"]).capitalize(),
                    row.get("target_workspace_name") or "",
                    row["target_item_type"],
                    row["target_item_name"],
                    row["target_schema_name"],
                    row.get("target_object_name") or "",
                ]
            )
    catalogues = table(
        "catalogues",
        ("code", "label", "reference"),
        [
            (str(code), m.label, f"{m.workspace}/Warehouse/{m.catalogue_name}")
            for code, m in enumerate(entries, start=1)
        ],
    )
    body = "".join(table(name, cols, vals) for name, (cols, vals) in merged.items())
    return (
        body
        + catalogues
        + table(
            "shortcuts",
            (
                "item",
                "schema",
                "object",
                "type",
                "workspace",
                "targettype",
                "target",
                "targetschema",
                "targetobject",
            ),
            shortcuts,
        )
    )


def estates():
    return {
        "a failed central table": members(central(), sales()),
        "a reloaded central table": members(
            central("succeeded", LATER), sales(revenue_loaded=EARLIER)
        ),
        "a consumer loaded after it": members(
            central("succeeded", EARLIER), sales(revenue_loaded=LATER)
        ),
        "reading back through another catalogue": alpha_and_beta(),
        "a cycle across catalogues": _cycle_members(summary=LATER, live=EARLIER),
        "a failed member of a cycle across catalogues": _cycle_members(
            summary=LATER, live=EARLIER, live_result="failed"
        ),
    }


@pytest.mark.parametrize("name", list(estates()))
@weaver_test()
def test_the_dashboard_finds_what_joined_health_finds(name):
    node = _node()
    if node is None:
        pytest.skip("Node.js is not on PATH; set WEAVER_NODE to run the renderer")
    entries = estates()[name]
    as_of = NOW - timedelta(days=1)
    report = assess_joined(entries, as_of=as_of, generated_at=NOW)

    codes = {m.label: code for code, m in enumerate(entries, start=1)}
    dags = {m.label: m.dag for m in entries}

    def identity(label, object_id):
        node = dags[label].by_id[object_id]
        schema, object_name = catalogue_columns(node.identity)
        return f"{node.item}{OWNER}{codes[label]}|{schema or ''}|{object_name or ''}"

    expected = set()
    for each in report.catalogues:
        for section in each.report.sections:
            for finding in section.findings:
                if (
                    finding.code in UNOBSERVED
                    or finding.object_id not in dags[each.label].by_id
                ):
                    continue
                expected.add(
                    (
                        finding.area,
                        finding.code,
                        finding.severity,
                        identity(each.label, finding.object_id),
                    )
                )
    # A cycle across catalogues is reported once, on the joined report; the
    # Dashboard reports it on its first member.
    for cycle in report.cycles:
        first = min(identity(*member.split("::", 1)) for member in cycle)
        expected.add(("build", "dependency_cycle", "green", first))

    result = subprocess.run(
        [node, "-e", ASSESS, str(RENDERER), str(round(as_of.timestamp() * 1000))],
        input=joined_payload(entries),
        capture_output=True,
        encoding="utf-8",
        timeout=60,
        check=True,
    )
    seen = json.loads(result.stdout)

    assert seen["problems"] == []
    assert {tuple(f) for f in seen["findings"]} == expected
