"""The Catalogue Dashboard's model over the catalogues it reads.

The fragment's measures read catalogue tables through table macros, so one set
of measures serves both storage modes. Direct Lake reads one table per
catalogue and relation over OneLake; Import reads one table per relation with
a partition per catalogue.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .errors import CommandError

DIRECT_LAKE = "directLake"
IMPORT = "import"
MODES = (DIRECT_LAKE, IMPORT)
#: Direct Lake reads at most this many catalogues; more require Import.
DIRECT_LAKE_CATALOGUES = 10
#: The longest page measure the Dashboard returns. A DAX text value cannot
#: exceed 2^21 characters.
PAGE_BUDGET = 2_000_000

#: The model table each catalogue relation is read as.
RELATIONS = {
    "Lineage node": "LineageNode",
    "Lineage edge": "LineageEdge",
    "Installation": "Installation",
    "Registry": "Registry",
    "Dependency": "Dependency",
    "Load status": "LoadStatus",
    "Log": "Log",
    "Load statistic": "LoadStatistic",
    "Test status": "TestStatus",
    "Test dictionary": "TestDictionary",
    "Schema dictionary": "SchemaDictionary",
    "Table dictionary": "TableDictionary",
    "Folder dictionary": "FolderDictionary",
    "Column dictionary": "ColumnDictionary",
    "Key dictionary": "KeyDictionary",
    "Foreign key dictionary": "ForeignKeyDictionary",
    "Semantic model": "SemanticModel",
    "Semantic model table": "SemanticModelTable",
    "Semantic model column": "SemanticModelColumn",
    "Semantic model measure": "SemanticModelMeasure",
    "Semantic model relationship": "SemanticModelRelationship",
    "Shortcut": "Shortcut",
    "Mirror": "Mirror",
}
#: Relations a catalogue holds only once something has happened to it: a
#: catalogue that has never been a mirror has no ``_.Mirror``.
OPTIONAL = frozenset({"Mirror"})


@dataclass(frozen=True)
class DashboardSource:
    """One catalogue the Dashboard reads."""

    #: How the Dashboard names the catalogue: its workspace, or the reference
    #: where one workspace holds two catalogues read.
    label: str
    #: ``Workspace/Warehouse/Name``.
    reference: str
    workspace: str
    workspace_id: str
    warehouse: str
    item_id: str
    #: The Warehouse's SQL endpoint, which Import reads.
    server: str | None = None
    #: Each catalogue table's columns and their SQL types.
    columns: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    @property
    def alias(self) -> str:
        """A name part that stays with the catalogue whatever the order given."""

        identity = f"{self.workspace_id}/{self.item_id}".casefold()
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:6]


def declared_columns(table: str) -> dict[str, str]:
    """This Weaver version's columns of a catalogue table, with SQL types."""

    from .catalogue.tables import TABLES_BY_NAME

    declared = TABLES_BY_NAME[table]
    types = {column.public_name: column.warehouse_type for column in declared.columns}
    return {name: types.get(name, "datetime2(6)") for name in declared.public_columns}


def template() -> str:
    from .catalogue_dashboard import DASHBOARD
    from .fragments import DASHBOARD as FRAGMENT
    from .fragments import fragment_files

    return fragment_files(FRAGMENT)[f"{DASHBOARD}.tmdl"].decode("utf-8")


_REFERENCE = re.compile(r"'((?:[^']|'')+)'\[([^\]]+)\]")


def required_columns(text: str | None = None) -> dict[str, tuple[str, ...]]:
    """Each catalogue table's columns the measures read, by catalogue table."""

    text = template() if text is None else text
    found: dict[str, set[str]] = {}
    for table, column in _REFERENCE.findall(text):
        table = table.replace("''", "'")
        if table in RELATIONS:
            found.setdefault(RELATIONS[table], set()).add(column)
    return {table: tuple(sorted(columns)) for table, columns in sorted(found.items())}


def missing_columns(source: DashboardSource) -> dict[str, tuple[str, ...]]:
    """What the measures read that ``source`` does not hold, by catalogue table."""

    missing = {}
    for table, columns in required_columns().items():
        if table in OPTIONAL and table not in source.columns:
            continue
        held = {name.casefold() for name in source.columns.get(table, {})}
        absent = tuple(c for c in columns if c.casefold() not in held)
        if absent:
            missing[table] = absent
    return missing


# --- measure macros ---------------------------------------------------------


def _arguments(text: str, start: int) -> tuple[list[str], int]:
    """The top-level arguments of the call whose ``(`` is at ``start``."""

    depth, i, begun, found = 0, start, start + 1, []
    while i < len(text):
        c = text[i]
        if c in "\"'[":
            close = {'"': '"', "'": "'", "[": "]"}[c]
            i += 1
            while i < len(text):
                if text[i] == close:
                    if close != "]" and text[i + 1 : i + 2] == close:
                        i += 2
                        continue
                    break
                i += 1
        elif c in "({":
            depth += 1
        elif c in ")}":
            depth -= 1
            if depth == 0:
                found.append(text[begun:i].strip())
                return found, i + 1
        elif c == "," and depth == 1:
            found.append(text[begun:i].strip())
            begun = i + 1
        i += 1
    raise AssertionError(f"unbalanced call at {text[start - 20 : start + 40]!r}")


def _split_top(text: str, separator: str) -> list[str]:
    parts, depth, begun, i = [], 0, 0, 0
    while i < len(text):
        c = text[i]
        if c in "\"'[":
            close = {'"': '"', "'": "'", "[": "]"}[c]
            i += 1
            while i < len(text) and text[i] != close:
                i += 1
        elif c in "({":
            depth += 1
        elif c in ")}":
            depth -= 1
        elif depth == 0 and text.startswith(separator, i):
            parts.append(text[begun:i].strip())
            begun = i + len(separator)
            i = begun
            continue
        i += 1
    parts.append(text[begun:].strip())
    return parts


def _dax_string(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _one_line(text: str) -> str:
    return " ".join(line.strip() for line in text.splitlines())


class _Expander:
    def __init__(self, sources: Sequence[DashboardSource], mode: str):
        self.sources = tuple(sources)
        self.mode = mode

    def holders(self, table: str) -> list[tuple[int, DashboardSource]]:
        """Each catalogue holding a relation, with its code."""

        relation = RELATIONS[table]
        return [
            (code, source)
            for code, source in enumerate(self.sources, start=1)
            if relation not in OPTIONAL or relation in source.columns
        ]

    def table_name(self, table: str, source: DashboardSource) -> str:
        return table if self.mode == IMPORT else f"{table} {source.alias}"

    def rename(self, text: str, table: str, source: DashboardSource) -> str:
        quoted = "'" + table.replace("'", "''") + "'"
        named = "'" + self.table_name(table, source).replace("'", "''") + "'"
        return text.replace(quoted, named)

    def catalogues(self, arguments: list[str]) -> str:
        head, columns = arguments[0], arguments[1:]
        table_part, _, where = head.partition(" WHERE ")
        table = table_part.strip().strip("'").replace("''", "'")
        if table not in RELATIONS:
            raise AssertionError(f"CATALOGUES reads {table!r}, not a catalogue table")
        filters = _split_top(where, "&&") if where else []
        projected = ", ".join(columns)
        holders = self.holders(table)
        if not holders:
            # No catalogue holds it: the same columns, and no rows.
            blank = ", ".join(f'{name}, ""' for name in columns[0::2])
            return f'FILTER(ROW("@catalogue", "", "@code", "", {blank}), FALSE())'
        if self.mode == IMPORT:
            quoted = "'" + table.replace("'", "''") + "'"
            body = (
                f'SELECTCOLUMNS({quoted}, "@catalogue", {quoted}[Catalogue], '
                f'"@code", {quoted}[Catalogue code], {projected})'
            )
            return f"CALCULATETABLE({body}, {', '.join(filters)})" if filters else body
        branches = []
        for code, source in holders:
            named = "'" + self.table_name(table, source).replace("'", "''") + "'"
            body = (
                f'SELECTCOLUMNS({named}, "@catalogue", {_dax_string(source.label)}, '
                f'"@code", "{code}", {self.rename(projected, table, source)})'
            )
            if filters:
                renamed = ", ".join(self.rename(f, table, source) for f in filters)
                body = f"CALCULATETABLE({body}, {renamed})"
            branches.append(body)
        return branches[0] if len(branches) == 1 else f"UNION({', '.join(branches)})"

    def sum_catalogues(self, arguments: list[str]) -> str:
        table = arguments[0].strip().strip("'").replace("''", "'")
        expression = arguments[1]
        holders = self.holders(table)
        if not holders:
            return "0"
        if self.mode == IMPORT:
            return f"({expression})"
        return (
            "("
            + " + ".join(
                f"({self.rename(expression, table, source)})" for _, source in holders
            )
            + ")"
        )

    def expand(self, text: str) -> str:
        macros = {
            "SUM_CATALOGUES(": self.sum_catalogues,
            "CATALOGUES(": self.catalogues,
            "TEST_SUMMARY(": _test_summary,
            "LOAD_SUMMARY(": _load_summary,
        }
        pattern = re.compile(
            r"(?<![A-Z_])(" + "|".join(re.escape(m) for m in macros) + ")"
        )
        while True:
            found = pattern.search(text)
            if not found:
                return text
            start = found.end() - 1
            arguments, end = _arguments(text, start)
            arguments = [self.expand(argument) for argument in arguments]
            text = (
                text[: found.start()] + macros[found.group(1)](arguments) + text[end:]
            )


def _epoch(value: str) -> str:
    return f'IF(ISBLANK({value}), "", FORMAT(({value} - DATE(1970, 1, 1)) * 86400000, "0"))'


def _test_summary(arguments: list[str]) -> str:
    rows, since = arguments
    return (
        f"CONCATENATEX(GROUPBY(FILTER({rows}, [@end] >= {since}), [@code], [@targettype], "
        "[@target], [@schema], [@object], "
        '"@runs", SUMX(CURRENTGROUP(), 1), '
        '"@total", SUMX(CURRENTGROUP(), [@duration]), '
        '"@longest", MAXX(CURRENTGROUP(), [@duration]), '
        '"@failures", SUMX(CURRENTGROUP(), [@failed]), '
        '"@lastend", MAXX(CURRENTGROUP(), [@end])), '
        "_r & [@code] & _f & [@targettype] & _f & [@target] & _f & [@schema] & _f & [@object] "
        "& _f & [@runs] & _f & [@total] & _f & [@longest] & _f & [@failures] & _f & "
        + _epoch("[@lastend]")
        + ', "")'
    )


def _load_summary(arguments: list[str]) -> str:
    rows, since = arguments
    timed = "NOT ISBLANK([@read]) && [@duration] > 0"
    return (
        f"CONCATENATEX(GROUPBY(FILTER({rows}, [@end] >= {since}), [@code], [@item], "
        "[@schema], [@object], "
        '"@n", SUMX(CURRENTGROUP(), 1), '
        '"@total", SUMX(CURRENTGROUP(), [@duration]), '
        '"@longest", MAXX(CURRENTGROUP(), [@duration]), '
        '"@tread", SUMX(CURRENTGROUP(), [@read]), '
        '"@tinserted", SUMX(CURRENTGROUP(), [@inserted]), '
        '"@tupdated", SUMX(CURRENTGROUP(), [@updated]), '
        '"@tdeleted", SUMX(CURRENTGROUP(), [@deleted]), '
        '"@trejected", SUMX(CURRENTGROUP(), [@rejected]), '
        '"@reloads", SUMX(CURRENTGROUP(), [@reload]), '
        '"@skips", SUMX(CURRENTGROUP(), [@skip]), '
        f'"@timedread", SUMX(CURRENTGROUP(), IF({timed}, [@read])), '
        f'"@timedduration", SUMX(CURRENTGROUP(), IF({timed}, [@duration])), '
        '"@lastend", MAXX(CURRENTGROUP(), [@end])), '
        "_r & [@item] & _q & [@code] & _f & [@schema] & _f & [@object] "
        "& _f & [@n] & _f & [@total] & _f & [@longest] & _f & [@tread] & _f & [@tinserted] "
        "& _f & [@tupdated] & _f & [@tdeleted] & _f & [@trejected] & _f & [@reloads] "
        "& _f & [@skips] & _f & [@timedread] & _f & [@timedduration] & _f & "
        + _epoch("[@lastend]")
        + ', "")'
    )


def page_expression(name: str, data: str) -> str:
    """A page measure: its data, or a small page saying it is too large."""

    f, r, t, less = (f"UNICHAR({n})" for n in (57345, 57346, 57347, 57344))
    return "\n".join(
        (
            f'VAR _data = SUBSTITUTE({t} & "page" & {f} & "name" & {r} & "{name}" & {data}, "<", {less})',
            "VAR _size = LEN(_data) + LEN([Renderer])",
            f'VAR _small = {t} & "page" & {f} & "name" & {r} & "{name}" & {t} & "toolarge" & {f} & "size" & {f} & "budget" & {r} & _size & {f} & "{PAGE_BUDGET}"',
            "RETURN",
            '    "<div id=""wd-app"" class=""wd""></div><script type=""text/plain"" id=""wd-data"">"',
            f"        & IF(_size > {PAGE_BUDGET}, _small, _data)",
            '        & "</script>" & [Renderer]',
        )
    )


def catalogue_rows(sources: Sequence[DashboardSource]) -> str:
    """The catalogues section's rows, as a DAX text expression."""

    f, r = "UNICHAR(57345)", "UNICHAR(57346)"
    rows = [
        f'{r} & "{code}" & {f} & {_dax_string(s.label)} & {f} & {_dax_string(s.reference)}'
        for code, s in enumerate(sources, start=1)
    ]
    return "(" + " & ".join(rows) + ")" if rows else '""'


def expand_measures(text: str, sources: Sequence[DashboardSource], mode: str) -> str:
    """The fragment's measure table with every macro expanded."""

    expander = _Expander(sources, mode)
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        line = lines[i]
        page = re.match(r"^(\s*)measure '([^']+)' = PAGE\(", line)
        if page:
            indent = page.group(1)
            arguments, _ = _arguments(line, line.index("PAGE(") + 4)
            name = arguments[0].strip('"')
            body = page_expression(name, arguments[1])
            out.append(f"{indent}measure '{page.group(2)}' = ```")
            out.extend(indent * 2 + each for each in body.split("\n"))
            out.append(indent * 2 + "```")
            i += 1
            continue
        out.append(line)
        i += 1
    text = "\n".join(out)
    text = text.replace('"{mode}"', _dax_string(mode))
    # Import says when it last read the catalogues; Direct Lake reads them live.
    text = text.replace(
        '"{imported}"',
        "FORMAT((MAX('Installation'[Imported at]) - DATE(1970, 1, 1)) * 86400000, \"0\")"
        if mode == IMPORT
        else '""',
    )
    text = text.replace('"{catalogues}"', catalogue_rows(sources))
    text = text.replace('"{several}"', '"1"' if len(sources) > 1 else '"0"')
    return _expand_blocks(text, expander)


def _expand_blocks(text: str, expander: _Expander) -> str:
    """Expand macros, keeping each macro call's expansion on one line."""

    pattern = re.compile(
        r"(?<![A-Z_])(SUM_CATALOGUES|CATALOGUES|TEST_SUMMARY|LOAD_SUMMARY)\("
    )
    while True:
        found = pattern.search(text)
        if not found:
            return text
        start = found.end() - 1
        _, end = _arguments(text, start)
        call = _one_line(text[found.start() : end])
        text = text[: found.start()] + expander.expand(call) + text[end:]


# --- tables ------------------------------------------------------------------


def _column(name: str, sql_type: str, relation: str) -> dict:
    from .semantic_models.binding import semantic_type

    return {
        "name": name,
        "dataType": semantic_type(sql_type, relation, name),
        "sourceColumn": name,
    }


def _source_columns(source: DashboardSource, table: str, wanted) -> list[dict]:
    held = {
        name.casefold(): (name, kind)
        for name, kind in source.columns.get(table, {}).items()
    }
    columns = []
    for name in wanted:
        if name.casefold() not in held:
            raise CommandError(
                f"{source.reference} has no column {name!r} in _.{table}. Build a "
                "project with this version of Weaver into that catalogue first."
            )
        actual, kind = held[name.casefold()]
        columns.append(_column(actual, kind, table))
    return columns


def _onelake(source: DashboardSource) -> str:
    return "Catalogue " + source.alias


def _m_string(value: str) -> str:
    from .semantic_models.binding import m_string

    return m_string(value)


def catalogue_tables(
    sources: Sequence[DashboardSource], mode: str
) -> tuple[list, list]:
    """The model's expressions and catalogue tables, as TMSL-shaped objects."""

    required = required_columns()
    expressions, tables = [], []
    if mode == DIRECT_LAKE:
        for source in sources:
            expressions.append(
                {
                    "name": _onelake(source),
                    "kind": "m",
                    "expression": "\n".join(
                        (
                            "let",
                            "    Source = AzureStorage.DataLake("
                            + _m_string(
                                "https://onelake.dfs.fabric.microsoft.com/"
                                f"{source.workspace_id}/{source.item_id}"
                            )
                            + ", [HierarchicalNavigation=true])",
                            "in",
                            "    Source",
                        )
                    ),
                }
            )
        for model_table, relation in RELATIONS.items():
            for source in sources:
                if relation in OPTIONAL and relation not in source.columns:
                    continue
                name = f"{model_table} {source.alias}"
                tables.append(
                    {
                        "name": name,
                        "isHidden": True,
                        "columns": _source_columns(
                            source, relation, required.get(relation, ())
                        ),
                        "partitions": [
                            {
                                "name": name,
                                "mode": "directLake",
                                "source": {
                                    "type": "entity",
                                    "entityName": relation,
                                    "schemaName": "_",
                                    "expressionSource": _onelake(source),
                                },
                            }
                        ],
                    }
                )
        return expressions, tables
    for model_table, relation in RELATIONS.items():
        wanted = required.get(relation, ())
        columns = None
        partitions = []
        for code, source in enumerate(sources, start=1):
            if relation in OPTIONAL and relation not in source.columns:
                continue
            found = _source_columns(source, relation, wanted)
            columns = columns or found
            if not source.server:
                raise CommandError(
                    f"{source.reference} has no SQL endpoint to import from."
                )
            names = "{" + ", ".join(_m_string(c["sourceColumn"]) for c in found) + "}"
            partitions.append(
                {
                    "name": f"{model_table} {source.alias}",
                    "mode": "import",
                    "source": {
                        "type": "m",
                        "expression": "\n".join(
                            (
                                "let",
                                f"    Source = Sql.Database({_m_string(source.server)}, {_m_string(source.warehouse)}),",
                                f'    Data = Source{{[Schema="_", Item={_m_string(relation)}]}}[Data],',
                                f"    Kept = Table.SelectColumns(Data, {names}),",
                                f'    Labelled = Table.AddColumn(Kept, "Catalogue", each {_m_string(source.label)}, type text),',
                                f'    Coded = Table.AddColumn(Labelled, "Catalogue code", each "{code}", type text)'
                                + (
                                    ',\n    Stamped = Table.AddColumn(Coded, "Imported at", each DateTimeZone.RemoveZone(DateTimeZone.UtcNow()), type datetime)'
                                    if relation == "Installation"
                                    else ""
                                ),
                                "in",
                                "    Stamped"
                                if relation == "Installation"
                                else "    Coded",
                            )
                        ),
                    },
                }
            )
        if not partitions:
            continue
        tables.append(
            {
                "name": model_table,
                "isHidden": True,
                "columns": [
                    *(columns or []),
                    {
                        "name": "Catalogue",
                        "dataType": "string",
                        "sourceColumn": "Catalogue",
                    },
                    {
                        "name": "Catalogue code",
                        "dataType": "string",
                        "sourceColumn": "Catalogue code",
                    },
                    *(
                        [
                            {
                                "name": "Imported at",
                                "dataType": "dateTime",
                                "sourceColumn": "Imported at",
                            }
                        ]
                        if relation == "Installation"
                        else []
                    ),
                ],
                "partitions": partitions,
            }
        )
    return expressions, tables


def model_text(sources: Sequence[DashboardSource], mode: str) -> str:
    """The Dashboard model's TMDL over ``sources``."""

    from .semantic_models.render import render_object

    if mode not in MODES:
        raise AssertionError(f"unknown Dashboard mode {mode!r}")
    text = template()
    head, _, measures = text.partition(
        "\n/// Every measure of the Catalogue Dashboard."
    )
    measures = "/// Every measure of the Catalogue Dashboard." + measures
    expressions, tables = catalogue_tables(sources, mode)
    unit = "    "
    rendered = [head.rstrip("\n")]
    for expression in expressions:
        rendered.append(render_object("expression", expression, unit=unit).rstrip("\n"))
    for table in tables:
        rendered.append(render_object("table", table, unit=unit).rstrip("\n"))
    rendered.append(expand_measures(measures, sources, mode).rstrip("\n"))
    return "\n\n".join(rendered) + "\n"


__all__ = [
    "DIRECT_LAKE",
    "DIRECT_LAKE_CATALOGUES",
    "DashboardSource",
    "IMPORT",
    "MODES",
    "OPTIONAL",
    "PAGE_BUDGET",
    "RELATIONS",
    "declared_columns",
    "model_text",
    "required_columns",
]
