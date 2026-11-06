"""A dependent Python Table opens every file a Folder published in the same load.

A Files mount caches a failed lookup. A path looked up through it while absent
stays absent there for minutes after OneLake creates it, although a mount made
afterwards sees it at once. The Folder here looks up its destination through
the mount before publishing, as authored code that skips files it already has
does, and the Table then opens what was published with ordinary ``pathlib``.

The second load also deletes a file created over ``abfss://`` after the mount
looked it up, which the mount still reports absent.
"""

from __future__ import annotations

from pathlib import Path

from support.weaver_test import weaver_test

import weaver

ITEM = "Lakehouse/Documents"
BATCH = 40

FOLDER = f'''\
"""
Folder ID: Raw.Documents

Description: Documents and their sidecars.

Lineage: Generated in the load.

File key: "docs/**/*"

Incremental: true
"""

import json

import notebookutils

from weaver import Folder


class Raw__Documents(Folder):
    def read(self):
        destination = self.path()
        held = self.current_files()
        first = len([path for path in held if path.suffix == ".pdf"])
        files = {{}}
        for number in range(first, first + {BATCH}):
            name = f"docs/2024-{{number:04d}}.pdf"
            files[name] = b"%PDF-1.4 " + str(number).encode() * 64
            files[name + ".url.json"] = json.dumps({{"number": number}}).encode()
        files["docs/_marker"] = str(first + {BATCH}).encode()
        if first:
            files["docs/2024-0000.pdf.url.json"] = b'{{"number": 0, "revised": true}}'

        # Look up what is already there through the mount, before publication.
        list(destination.glob("**/*"))
        for name in files:
            (destination / name).exists()

        deletes = []
        if first:
            stale = destination / "docs/stale.txt"
            stale.exists()
            notebookutils.fs.put(self.spark_path() + "/docs/stale.txt", "stale", True)
            if stale.exists():
                raise RuntimeError("the mount sees docs/stale.txt; nothing is stale")
            deletes.append("docs/stale.txt")

        staging = self.staging_folder()
        for name, data in files.items():
            target = staging.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return staging, deletes
'''

TABLE = '''\
"""
Table ID: Raw.DocumentIndex

Description: One row per document file the Folder published.

Lineage: $Files/Raw.Documents

Primary key: Name

Incremental: true

Schema:
  Name: string
  Bytes: long
  Sha256: string
"""

import hashlib

import notebookutils
from Files.Raw__Documents import Raw__Documents

from weaver import Table


class Raw__DocumentIndex(Table):
    def read(self):
        folder = Raw__Documents(self)
        root = folder.path()
        rows = []
        for path in sorted(folder.files_since(self.bookmark())):
            data = path.read_bytes()
            name = path.relative_to(root).as_posix()
            rows.append((name, len(data), hashlib.sha256(data).hexdigest()))
        globbed = {
            path.relative_to(root).as_posix()
            for path in root.glob("docs/**/*")
            if path.is_file()
        }
        omitted = sorted({row[0] for row in rows} - globbed)
        if omitted:
            raise RuntimeError(f"glob omits {len(omitted)} published files: {omitted[:5]}")
        if notebookutils.fs.exists(folder.spark_path() + "/docs/stale.txt"):
            raise RuntimeError("OneLake still has the deleted docs/stale.txt")
        return self.spark.createDataFrame(rows, "Name string, Bytes long, Sha256 string")
'''


def write_repository(root: Path) -> Path:
    item = root / ITEM
    (item / "Files").mkdir(parents=True)
    (item / "Tables").mkdir()
    (item / "Files" / "Raw__Documents.py").write_text(FOLDER, "utf-8")
    (item / "Tables" / "Raw__DocumentIndex.py").write_text(TABLE, "utf-8")
    return root


@weaver_test(integration=True, resources={"rest", "tds", "livy", "onelake"})
def test_a_dependent_table_opens_every_file_a_folder_published_in_its_load(
    weaver_session,
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

    folder = f"load:Lakehouse/{target}/Files/Raw.Documents"
    table = f"load:Lakehouse/{target}/Tables/Raw.DocumentIndex"
    # The first load publishes into a destination that did not exist; the second
    # adds to one that does, revises one sidecar and deletes a file the mount
    # reports absent.
    for inserted, updated, deleted in ((2 * BATCH + 1, 0, 0), (2 * BATCH, 2, 1)):
        loaded = weaver.load([ITEM], session=weaver_session)
        assert loaded.succeeded, loaded.to_mapping()
        nodes = loaded.by_node
        published = nodes[folder].result
        indexed = nodes[table].result
        assert (
            published.rows_inserted,
            published.rows_updated,
            published.rows_deleted,
        ) == (inserted, updated, deleted)
        assert (indexed.rows_inserted, indexed.rows_updated) == (inserted, updated)
