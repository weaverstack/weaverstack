"""Public ``weaver.execute(...)``: ad hoc T-SQL, Spark SQL, Python or DAX.

.. code-block:: text

    tsql       Warehouse/<Item>       every result set, in order
    spark-sql  Lakehouse/<Item>       the last statement's result
    python     Lakehouse/<Item>       printed output, run in Fabric
    dax        SemanticModel/<Item>   one query's rows

The item resolves to its configured target, or else to the Fabric item of the
same name; no catalogue is read. Each result is read to ``limit`` rows where it
runs. Execution records nothing, so no bookmark or load state moves.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..declaration.model import LAKEHOUSE, SEMANTIC_MODEL, WAREHOUSE, WeaverItemId
from ..errors import CommandError, ExecuteError, IdentityError, OutcomeUnknown
from ..representation import ReportAlias

TSQL = "tsql"
SPARK_SQL = "spark-sql"
PYTHON = "python"
DAX = "dax"

#: The item type each engine runs against.
ENGINES = {
    TSQL: WAREHOUSE,
    SPARK_SQL: LAKEHOUSE,
    PYTHON: LAKEHOUSE,
    DAX: SEMANTIC_MODEL,
}

DEFAULT_LIMIT = 100

#: Printed Python output returned, in characters.
OUTPUT_LIMIT = 100_000


@dataclass(frozen=True)
class ResultSet:
    """Rows read to the limit; ``truncated`` when the result had more."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    truncated: bool = False

    def to_mapping(self) -> dict:
        return {
            "columns": list(self.columns),
            "rows": [list(row) for row in self.rows],
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class ExecuteResult(ReportAlias):
    """What ``source`` returned where it ran."""

    engine: str
    item: str
    target: str
    result_sets: tuple[ResultSet, ...] = ()
    #: Printed Python output.
    output: str | None = None
    output_truncated: bool = False
    seconds: float = 0.0
    limit: int = DEFAULT_LIMIT
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_mapping(self) -> dict:
        mapping: dict[str, Any] = {
            "status": "succeeded",
            "engine": self.engine,
            "item": self.item,
            "target": self.target,
            "limit": self.limit,
            "seconds": round(self.seconds, 3),
            "result_sets": [each.to_mapping() for each in self.result_sets],
        }
        if self.output is not None:
            mapping["output"] = self.output
            mapping["output_truncated"] = self.output_truncated
        return mapping


def execute(
    engine: str,
    item: str,
    command: str | None = None,
    *,
    file: str | Path | None = None,
    workspace: str | None = None,
    environment: str | None = None,
    workspace_config: str | Path | None = None,
    limit: int = DEFAULT_LIMIT,
    session=None,
) -> ExecuteResult:
    """Run ``command``, or the contents of ``file``, against one item.

    ``engine`` is ``tsql``, ``spark-sql``, ``python`` or ``dax``, and ``item``
    is the Weaver item it runs against, such as ``Warehouse/Curated``.

    T-SQL runs as one batch and returns every result set. Spark SQL runs its
    statements in order, with the Lakehouse attached, and returns the last
    one's result. Python runs in Fabric with ``spark`` attached to the
    Lakehouse and returns what it printed. DAX runs one query.

    A failure raises :class:`~weaver.errors.ExecuteError` with what the engine
    reported. When a request may have reached Fabric and its response was
    lost, :class:`~weaver.errors.OutcomeUnknown` says so; nothing is sent again.
    """

    from .items import uncatalogued_target
    from .workspace import operation_workspace

    kind = ENGINES.get(engine)
    if kind is None:
        raise CommandError(
            f"engine must be one of {', '.join(ENGINES)}, got {engine!r}"
        )
    target_item = _item(item, kind=kind, engine=engine)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise CommandError("limit must be a positive integer")
    text = _source(command, file)

    resolved = operation_workspace(
        "execute",
        workspace=workspace,
        environment=environment,
        workspace_config=workspace_config,
        session=session,
        needs_catalogue=False,
    )
    physical = uncatalogued_target(resolved, target_item).name

    from ..sessions.host import use_or_create_session

    with use_or_create_session(session, workspace=resolved) as opened:
        with opened.task("Execute", f"{engine} {target_item}"):
            started = time.monotonic()
            try:
                found = _RUN[engine](
                    opened, text, workspace=resolved, physical=physical, limit=limit
                )
            except OutcomeUnknown as exc:
                raise OutcomeUnknown(
                    f"{engine} on {target_item} did not report back, so it may "
                    f"have run: {exc}"
                ) from exc
            return ExecuteResult(
                engine=engine,
                item=str(target_item),
                target=physical,
                seconds=time.monotonic() - started,
                limit=limit,
                **found,
            )


def _item(text: str, *, kind: str, engine: str) -> WeaverItemId:
    try:
        parsed = WeaverItemId.parse(text)
    except (IdentityError, TypeError, ValueError):
        parsed = None
    if parsed is None or parsed.item_type != kind:
        raise CommandError(f"{engine} runs against a {kind}/Name item, got {text!r}")
    return parsed


def _source(command: str | None, file) -> str:
    if (command is None) == (file is None):
        raise CommandError("Give exactly one of command and file.")
    if file is None:
        text = command
    else:
        path = Path(file).expanduser()
        try:
            text = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            raise CommandError(f"File not found: {path}") from None
        except UnicodeDecodeError as exc:
            raise CommandError(f"{path} is not UTF-8 text: {exc}") from None
    if not text.strip():
        raise CommandError("There is nothing to execute.")
    return text


# --- engines -------------------------------------------------------------------


def _tsql(session, text: str, *, workspace, physical: str, limit: int) -> dict:
    from ..sql.errors import SqlExecutionError
    from ..targets import ItemRef, WarehouseTarget

    try:
        sets = session.query_tsql_limited(
            text,
            target=WarehouseTarget(ItemRef(physical)),
            limit=limit,
            workspace=workspace,
        )
    except OutcomeUnknown:
        raise
    except SqlExecutionError as exc:
        raise ExecuteError(f"T-SQL failed on {physical}: {exc}") from exc
    return {
        "result_sets": tuple(
            ResultSet(columns=each.columns, rows=each.rows, truncated=each.truncated)
            for each in sets
        )
    }


#: Fabric runs this with ``spark`` and ``emit`` defined, after ``_statements``
#: and ``_limit``; it imports no Weaver.
_SPARK_SQL_PROGRAM = """\
import traceback as _traceback
_columns, _rows, _failure = [], [], None
try:
    for _statement in _statements[:-1]:
        spark.sql(_statement)
    _frame = spark.sql(_statements[-1])
    _columns = list(_frame.columns)
    if _columns:
        _rows = [list(_row) for _row in _frame.limit(_limit + 1).collect()]
except Exception:
    _failure = _traceback.format_exc()
emit({
    "columns": _columns,
    "rows": _rows[:_limit],
    "truncated": len(_rows) > _limit,
    "error": _failure,
})
"""


def _spark_sql_program(statements, limit: int) -> str:
    return (
        f"_statements = {list(statements)!r}\n_limit = {limit!r}\n" + _SPARK_SQL_PROGRAM
    )


def _spark_sql(session, text: str, *, workspace, physical: str, limit: int) -> dict:
    from ..sql_statements import split_statements

    statements = [each for each in split_statements(text) if each.strip()]
    if not statements:
        raise CommandError("There is nothing to execute.")
    found = session.execute_source(
        _spark_sql_program(statements, limit),
        lakehouse=physical,
        name="execute.spark_sql",
        workspace=workspace,
    )
    if found.get("error"):
        raise ExecuteError(f"Spark SQL failed on {physical}:\n{found['error']}")
    return {
        "result_sets": (
            ResultSet(
                columns=tuple(found["columns"]),
                rows=tuple(tuple(row) for row in found["rows"]),
                truncated=bool(found["truncated"]),
            ),
        )
    }


#: As the Spark SQL program, after ``_source`` and ``_limit``.
_PYTHON_PROGRAM = """\
import contextlib as _contextlib
import io as _io
import traceback as _traceback
_buffer = _io.StringIO()
_failure = None
try:
    with _contextlib.redirect_stdout(_buffer):
        exec(compile(_source, "<execute>", "exec"), {"spark": spark})
except BaseException:
    _failure = _traceback.format_exc()
_output = _buffer.getvalue()
emit({
    "output": _output[:_limit],
    "truncated": len(_output) > _limit,
    "error": _failure,
})
"""


def _python_program(source: str, limit: int) -> str:
    return f"_source = {source!r}\n_limit = {limit!r}\n" + _PYTHON_PROGRAM


def _python(session, text: str, *, workspace, physical: str, limit: int) -> dict:
    found = session.execute_source(
        _python_program(text, OUTPUT_LIMIT),
        lakehouse=physical,
        name="execute.python",
        workspace=workspace,
    )
    if found.get("error"):
        printed = found.get("output") or ""
        before = f"Printed before it failed:\n{printed}\n" if printed else ""
        raise ExecuteError(f"Python failed in Fabric:\n{before}{found['error']}")
    return {
        "output": found.get("output") or "",
        "output_truncated": bool(found.get("truncated")),
    }


def _dax(session, text: str, *, workspace, physical: str, limit: int) -> dict:
    from ..fabric.client import FabricError
    from ..targets import ItemRef

    model = session.semantic_model(ItemRef(physical), workspace=workspace)
    try:
        rows = model.query_dax(text)
    except OutcomeUnknown:
        raise
    except FabricError as exc:
        raise ExecuteError(f"DAX failed on {physical}: {exc}") from exc
    # Power BI returns the whole response; the limit applies to what is kept.
    columns = tuple(rows[0]) if rows else ()
    return {
        "result_sets": (
            ResultSet(
                columns=columns,
                rows=tuple(
                    tuple(row.get(column) for column in columns) for row in rows[:limit]
                ),
                truncated=len(rows) > limit,
            ),
        )
    }


_RUN = {TSQL: _tsql, SPARK_SQL: _spark_sql, PYTHON: _python, DAX: _dax}


__all__ = ["DEFAULT_LIMIT", "ENGINES", "ExecuteResult", "ResultSet", "execute"]
