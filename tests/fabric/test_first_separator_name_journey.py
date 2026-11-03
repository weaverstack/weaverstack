"""An object name holding ``__`` past the separator, built and loaded in Fabric.

The Python Table's class and the Spark SQL Table's generated module are both
named ``Agency__TitleMap__…``; Fabric reads each back to its identity when it
loads, and the Spark SQL Table's relation reference crosses the installed graph.
"""

from __future__ import annotations

from pathlib import Path

from support.weaver_test import weaver_test

import weaver

ITEM = "Lakehouse/Agency"

HISTORICAL = '''\
"""
Table ID: Agency.TitleMap__Historical

Description: Title codes, as they were.

Lineage: A fixed list.

Primary key: Code

Schema:
  Code: string
  Value: integer
"""

from weaver import Table


class Agency__TitleMap__Historical(Table):
    def read(self):
        return self.spark.sql(
            "SELECT 'A' AS Code, 1 AS Value UNION ALL SELECT 'B' AS Code, 2 AS Value"
        )
'''

DAILY = """\
/*
Table ID: Agency.TitleMap__Daily

Description: Title codes, read from their history.

Lineage: Agency.TitleMap__Historical.

Dependencies:
  - Agency.TitleMap__Historical

Primary key: Code

Schema:
  Code: string
  Value: integer
*/
select Code, Value from Agency.TitleMap__Historical;
"""


def write_repository(root: Path) -> Path:
    tables = root / ITEM / "Tables"
    tables.mkdir(parents=True)
    (tables / "Agency__TitleMap__Historical.py").write_text(HISTORICAL, "utf-8")
    (tables / "Agency.TitleMap__Daily.sql").write_text(DAILY, "utf-8")
    return root


@weaver_test(integration=True, resources={"rest", "tds", "livy", "onelake"})
def test_an_object_name_with_a_later_separator_builds_and_loads(
    weaver_session,
    livy_session,
    fabric_workspace,
    fabric_target_lakehouse,
    fabric_empty_lakehouse,
    fabric_lakehouse_cleanup,
    fabric_initialise_catalogue,
    tmp_path,
):
    target = fabric_target_lakehouse.name
    fabric_lakehouse_cleanup(target)
    fabric_empty_lakehouse(target)
    fabric_initialise_catalogue()

    built = weaver.build(
        str(write_repository(tmp_path)),
        items=[f"{ITEM}=Lakehouse/{target}"],
        session=weaver_session,
    )
    assert built.succeeded, built
    loaded = weaver.load([ITEM], session=weaver_session)
    assert loaded.succeeded, loaded

    prefix = f"load:Lakehouse/{target}/Tables/Agency."
    assert {f"{prefix}TitleMap__Historical", f"{prefix}TitleMap__Daily"} <= set(
        loaded.by_node
    )
    daily = f"`{fabric_workspace.workspace}`.`{target}`.`Agency`.`TitleMap__Daily`"
    seen = livy_session.run(
        f"rows = spark.sql('SELECT Code, Value FROM {daily} ORDER BY Code').collect()\n"
        "emit([list(row) for row in rows])\n"
    ).payload
    assert seen == [["A", 1], ["B", 2]]

    health = weaver.health([ITEM], session=weaver_session)
    assert not [
        finding
        for finding in health.build.findings
        if "dependency" in finding.message.casefold()
    ], health.build.findings
