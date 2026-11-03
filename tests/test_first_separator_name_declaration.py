"""``Schema__Object`` splits at its first ``__``; a schema cannot contain one."""

from __future__ import annotations

import pytest
from support.weaver_test import weaver_test
from test_item_repository_declaration import (
    _estate,
    _table,
    _warehouse_table,
    _write,
)

from weaver.declaration import parse_item_repository
from weaver.declaration.metadata import DAX, PYTHON, SQL, ObjectId
from weaver.declaration.model import WeaverDocumentId, split_qualified_name
from weaver.declaration.source import object_id_for_filename, python_id_parts
from weaver.errors import DiscoveryError
from weaver.locations import Location

#: Names valid before the change, and what they meant then.
UNCHANGED = [
    ("Sales__Order", ("Sales", "Order")),
    ("_Sales__Order", ("_Sales", "Order")),
    ("Sales___Order", ("Sales", "_Order")),
    ("___Load", ("_", "Load")),
    ("Sales_Region__Order", ("Sales_Region", "Order")),
]

#: Names a later ``__`` now keeps in the object.
SEPARATED = [
    ("Agency__TitleMap__Historical", ("Agency", "TitleMap__Historical")),
    ("Agency__TitleMap__", ("Agency", "TitleMap__")),
    ("___Load__Archive", ("_", "Load__Archive")),
]

NOT_NAMES = ["Sales", "Sales__", "__Order", ""]


@pytest.mark.parametrize("name, parts", UNCHANGED + SEPARATED)
@weaver_test()
def test_a_name_splits_at_its_first_separator(name, parts):
    assert split_qualified_name(name) == parts
    assert python_id_parts(name) == list(parts)


@pytest.mark.parametrize("name", NOT_NAMES)
@weaver_test()
def test_a_name_without_both_parts_is_not_split(name):
    assert split_qualified_name(name) is None


@pytest.mark.parametrize("name, parts", UNCHANGED + SEPARATED)
@weaver_test()
def test_a_class_reads_its_identity_by_the_parsers_rule(name, parts):
    from weaver.objects import _identity

    assert _identity(name) == parts


@pytest.mark.parametrize("name, parts", UNCHANGED + SEPARATED)
@weaver_test()
def test_a_generated_class_name_reads_back_as_its_object(name, parts):
    from weaver.declaration.spark_sql_module import class_name
    from weaver.objects import _identity

    generated = class_name(ObjectId(*parts))

    assert _identity(generated) == parts


# --- filenames -----------------------------------------------------------------


@weaver_test()
def test_a_python_filename_keeps_later_separators_in_the_object():
    assert object_id_for_filename(
        "Tables/Agency__TitleMap__Historical.py", PYTHON
    ) == ObjectId("Agency", "TitleMap__Historical")


@pytest.mark.parametrize(
    "filename, language",
    [
        ("Agency.TitleMap__Historical.sql", SQL),
        ("Agency.TitleMap__Historical.dax", DAX),
    ],
)
@weaver_test()
def test_a_sql_or_dax_object_name_may_contain_a_separator(filename, language):
    assert object_id_for_filename(filename, language) == ObjectId(
        "Agency", "TitleMap__Historical"
    )


@weaver_test()
def test_a_sql_filename_in_python_spelling_is_still_refused():
    with pytest.raises(DiscoveryError, match="must be Schema.Object.sql"):
        object_id_for_filename("Agency__TitleMap.sql", SQL)


@pytest.mark.parametrize(
    "filename, language",
    [("Agency__Archive.TitleMap.sql", SQL), ("Agency__Archive.TitleMap.dax", DAX)],
)
@weaver_test()
def test_a_schema_containing_a_separator_is_refused(filename, language):
    with pytest.raises(DiscoveryError, match="schema name 'Agency__Archive' cannot"):
        object_id_for_filename(filename, language)


@weaver_test()
def test_a_schema_document_containing_a_separator_is_refused():
    from weaver.declaration.schemas import read_schema_document

    with pytest.raises(DiscoveryError, match="cannot contain '__'"):
        read_schema_document(
            "Lakehouse/Raw/schemas/Agency__Archive.yml",
            b"Schema ID: Agency__Archive\nDescription: Archive.\n",
        )


# --- through a repository ------------------------------------------------------


def _historical(root):
    _write(root, "Lakehouse/Raw/schemas/Agency.yml", "Schema ID: Agency\n")
    _write(
        root,
        "Lakehouse/Raw/Tables/Agency__TitleMap__Historical.py",
        _table("Agency.TitleMap__Historical"),
    )


@weaver_test()
def test_a_repository_object_keeps_its_full_object_name(tmp_path):
    root = _estate(tmp_path)
    _historical(root)

    repository = parse_item_repository(Location(str(root)))

    assert (
        WeaverDocumentId.parse("Lakehouse/Raw/Tables/Agency.TitleMap__Historical")
        in repository.source_documents
    )


@weaver_test()
def test_an_import_of_such_an_object_is_a_dependency(tmp_path):
    root = _estate(tmp_path)
    _historical(root)
    _write(
        root,
        "Lakehouse/Raw/Tables/Sales__Order.py",
        _table("Sales.Order").replace(
            "from weaver import Table",
            "from weaver import Table\n"
            "from Tables.Agency__TitleMap__Historical import "
            "Agency__TitleMap__Historical",
        ),
    )

    repository = parse_item_repository(Location(str(root)))

    producers = {
        str(edge.producer)
        for edge in repository.dependency_edges
        if str(edge.consumer) == "Lakehouse/Raw/Tables/Sales.Order"
    }
    assert "Lakehouse/Raw/Tables/Agency.TitleMap__Historical" in producers


@weaver_test()
def test_a_warehouse_object_name_may_contain_a_separator(tmp_path):
    root = _estate(tmp_path)
    _write(
        root,
        "Warehouse/Reporting/Sales.Customer__Historical.sql",
        _warehouse_table("Sales.Customer__Historical"),
    )

    repository = parse_item_repository(Location(str(root)))

    assert (
        WeaverDocumentId.parse("Warehouse/Reporting/Sales.Customer__Historical")
        in repository.source_documents
    )


# --- shortcuts -----------------------------------------------------------------


def _destinations(repository) -> set[str]:
    return {str(each.destination) for each in repository.shortcuts}


def _shortcut(name: str, shortcut_type: str, target: str) -> str:
    return (
        "from weaver import Shortcut\n\n"
        f"{name} = Shortcut(\n"
        f'    shortcut_type="{shortcut_type}",\n'
        '    target_type="physical",\n'
        f'    target="{target}",\n'
        ")\n"
    )


@weaver_test()
def test_a_shortcut_name_keeps_later_separators_in_the_object(tmp_path):
    root = _estate(tmp_path)
    _write(
        root,
        "Lakehouse/Curated/shortcuts.py",
        _shortcut(
            "Sales__Landed__Daily", "table", "Lakehouse/Raw/Tables/Sales.Customer"
        ),
    )

    repository = parse_item_repository(Location(str(root)))

    assert "Lakehouse/Curated/Tables/Sales.Landed__Daily" in _destinations(repository)


@weaver_test()
def test_a_schema_shortcut_containing_a_separator_is_refused(tmp_path):
    root = _estate(tmp_path)
    _write(
        root,
        "Lakehouse/Curated/shortcuts.py",
        _shortcut("Sales__Archive", "schema", "Lakehouse/Raw/Sales"),
    )

    with pytest.raises(DiscoveryError, match="cannot contain '__'"):
        parse_item_repository(Location(str(root)))


@weaver_test()
def test_a_warehouse_shortcut_round_trips_a_separated_object_name(tmp_path):
    root = _estate(tmp_path)
    _write(
        root,
        "Warehouse/Reporting/shortcuts.yml",
        "physical:\n"
        "  Warehouse/Reporting/Sales.Landed__Daily: "
        "Warehouse/Reference/Sales.Customer\n",
    )

    repository = parse_item_repository(Location(str(root)))

    assert "Warehouse/Reporting/Sales.Landed__Daily" in _destinations(repository)


@weaver_test()
def test_a_warehouse_shortcut_schema_containing_a_separator_is_refused(tmp_path):
    root = _estate(tmp_path)
    _write(
        root,
        "Warehouse/Reporting/shortcuts.yml",
        "physical:\n"
        "  Warehouse/Reporting/Sales__Archive.Landed: "
        "Warehouse/Reference/Sales.Customer\n",
    )

    with pytest.raises(DiscoveryError, match="cannot contain '__'"):
        parse_item_repository(Location(str(root)))


# --- an installed dependency reference ----------------------------------------


@pytest.mark.parametrize(
    "reference, python",
    [
        ("Tables.Agency__TitleMap__Historical", True),
        ("Files.Sales__Landing", True),
        (".Sales__Order", True),
        ("Sales__Customer", True),
        ("Agency.TitleMap__Historical", False),
        ("Sales.Order", False),
    ],
)
@weaver_test()
def test_only_an_area_qualified_reference_is_a_python_import(reference, python):
    from weaver.installed import _is_python_module_reference

    assert _is_python_module_reference(reference) is python


@weaver_test()
def test_an_installed_import_projects_back_to_its_full_object_name():
    from weaver.installed import _python_module_identity

    consumer = WeaverDocumentId.parse("Lakehouse/Raw/Tables/Sales.Order")

    assert str(
        _python_module_identity(consumer, "Tables.Agency__TitleMap__Historical")
    ) == ("Lakehouse/Raw/Tables/Agency.TitleMap__Historical")
