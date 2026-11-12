"""Answer the catalogue's generated projection from declared per-table doubles."""

from __future__ import annotations

import re

BRANCH = re.compile(
    r"SELECT (\d+) AS \[__weaver_table\], (.*?) FROM \((SELECT .*?)\) AS \[source\](?: UNION ALL |$)",
    re.DOTALL,
)
FIELD = re.compile(r"\[source\]\.\[([a-z_0-9]+)\] AS \[(c\d+)\]")
SLOT = re.compile(r"AS \[(c\d+)\]")


def projected_rows(statement, query):
    if not statement.startswith("SELECT 0 AS [__weaver_table], "):
        return None
    branches = list(BRANCH.finditer(statement))
    assert "".join(m.group(0) for m in branches) == statement
    result = []
    for branch in branches:
        ordinal, projection, source = branch.groups()
        fields = FIELD.findall(projection)
        empty = {slot: None for slot in SLOT.findall(projection)}
        for raw in query(source):
            result.append(
                {
                    "__weaver_table": int(ordinal),
                    **empty,
                    **{slot: raw.get(name) for name, slot in fields},
                }
            )
    return result


class ProjectedAnswers(dict):
    """Keep recording one request while answering its component table reads."""

    def get(self, key, default=None):
        if key in self:
            return super().get(key, default)
        lookup = super().get
        rows = projected_rows(key, lambda statement: lookup(statement, default))
        return default if rows is None else rows
