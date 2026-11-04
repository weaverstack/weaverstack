"""A dependent Python Table opens every file a Folder published in the same load.

A Files mount caches a failed lookup. A path looked up through it while absent
stays absent there for minutes after OneLake creates it, although a mount made
afterwards sees it at once. The Folder here looks up its destination through
the mount before publishing, as authored code that skips files it already has
does, and the Table then opens what was published with ordinary ``pathlib``.
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

        staging = self.staging_folder()
        for name, data in files.items():
            target = staging.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return staging, []
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
    # adds to one that does and revises one sidecar.
    for inserted, updated in ((2 * BATCH + 1, 0), (2 * BATCH, 2)):
        loaded = weaver.load([ITEM], session=weaver_session)
        assert loaded.succeeded, loaded.to_mapping()
        nodes = loaded.by_node
        published = nodes[folder].result
        indexed = nodes[table].result
        assert (published.rows_inserted, published.rows_updated) == (inserted, updated)
        assert (indexed.rows_inserted, indexed.rows_updated) == (inserted, updated)
