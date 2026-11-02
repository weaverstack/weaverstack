"""`weaver execute`: ad hoc T-SQL, Spark SQL, Python and DAX against one item."""

from __future__ import annotations

import json
import sys
import types

import pytest
from support.weaver_test import weaver_test

import weaver
from weaver.declaration.model import WeaverItemId
from weaver.errors import CommandError, ExecuteError, OutcomeUnknown
from weaver.operations.execute import (
    ExecuteResult,
    ResultSet,
    _python_program,
    _spark_sql_program,
)
from weaver.sessions.testing import TestSession
from weaver.workspaces import TargetDeclaration, Workspace

WORKSPACE = Workspace(
    workspace="Sales Analytics",
    targets={
        WeaverItemId.parse("Warehouse/Curated"): TargetDeclaration("Curated_Dev"),
        WeaverItemId.parse("Lakehouse/Landing"): TargetDeclaration("Landing_Dev"),
        WeaverItemId.parse("SemanticModel/Reporting"): TargetDeclaration(
            "Reporting_Dev"
        ),
    },
)


@pytest.fixture
def session():
    return TestSession(workspace=WORKSPACE)


def _calls(session, kind):
    return [call for call in session.calls if call.kind == kind]


# --- T-SQL ---------------------------------------------------------------------


@weaver_test()
def test_tsql_runs_against_the_configured_warehouse(session):
    session.answer_tsql("select 1 as Value", [{"Value": 1}])

    result = weaver.execute(
        "tsql", "Warehouse/Curated", "select 1 as Value", session=session
    )

    (call,) = _calls(session, "tsql")
    assert call.body == ["select 1 as Value"]
    assert call.detail["target"].warehouse.name == "Curated_Dev"
    assert result.target == "Curated_Dev"
    assert result.result_sets == (ResultSet(columns=("Value",), rows=((1,),)),)


@weaver_test()
def test_an_unconfigured_item_runs_against_the_item_of_its_name(session):
    weaver.execute("tsql", "Warehouse/Reference", "select 1", session=session)

    (call,) = _calls(session, "tsql")
    assert call.detail["target"].warehouse.name == "Reference"


@weaver_test()
def test_tsql_reads_to_the_limit(session):
    session.answer_tsql("select n", [{"n": n} for n in range(5)])

    result = weaver.execute(
        "tsql", "Warehouse/Curated", "select n", limit=3, session=session
    )

    (rows,) = result.result_sets
    assert rows.rows == ((0,), (1,), (2,))
    assert rows.truncated
    assert _calls(session, "tsql")[0].detail["limit"] == 3


@weaver_test()
def test_a_tsql_failure_says_what_the_warehouse_reported(session, monkeypatch):
    from weaver.sql.errors import SqlExecutionError

    def failing(*args, **kwargs):
        raise SqlExecutionError("Invalid object name 'dbo.Missing'.")

    monkeypatch.setattr(session, "query_tsql_limited", failing)

    with pytest.raises(ExecuteError, match="Invalid object name 'dbo.Missing'"):
        weaver.execute(
            "tsql", "Warehouse/Curated", "select * from dbo.Missing", session=session
        )


@weaver_test()
def test_a_lost_response_is_uncertain_and_not_retried(session, monkeypatch):
    from weaver.sql.errors import SqlOutcomeUnknown

    attempts = []

    def lost(*args, **kwargs):
        attempts.append(args)
        raise SqlOutcomeUnknown("connection reset")

    monkeypatch.setattr(session, "query_tsql_limited", lost)

    with pytest.raises(OutcomeUnknown, match="may have run"):
        weaver.execute(
            "tsql", "Warehouse/Curated", "delete from dbo.Order", session=session
        )
    assert len(attempts) == 1


# --- the limited T-SQL read ------------------------------------------------------


class _Cursor:
    """Result sets as a driver presents them; rows past what is fetched stay put."""

    def __init__(self, sets):
        self._sets = list(sets)
        self.fetched = []

    @property
    def description(self):
        columns, _rows = self._sets[0]
        return None if columns is None else [(name,) for name in columns]

    def fetchmany(self, size):
        _columns, rows = self._sets[0]
        self.fetched.append(size)
        return rows[:size]

    def fetchall(self):  # pragma: no cover - the limited read must not use it
        raise AssertionError("fetchall reads every row")

    def nextset(self):
        self._sets.pop(0)
        return bool(self._sets)


@weaver_test()
def test_each_result_set_is_fetched_to_one_past_the_limit():
    from weaver.sql.execution import LimitedRows, _limited_result_sets

    cursor = _Cursor(
        [
            (("a",), [(1,), (2,), (3,)]),
            (None, []),
            (("b", "c"), [(4, 5)]),
        ]
    )

    sets = _limited_result_sets(cursor, 2)

    assert sets == [
        LimitedRows(columns=("a",), rows=((1,), (2,)), truncated=True),
        LimitedRows(columns=("b", "c"), rows=((4, 5),), truncated=False),
    ]
    assert cursor.fetched == [3, 3]


# --- Spark SQL -----------------------------------------------------------------


class _Frame:
    def __init__(self, columns, rows):
        self.columns = columns
        self._rows = rows
        self.limited = None

    def limit(self, size):
        self.limited = size
        return _Frame(self.columns, self._rows[:size])

    def collect(self):
        return self._rows


class _Spark:
    def __init__(self, frames=None, failing=None):
        self.statements = []
        self.frames = frames or {}
        self.failing = failing

    def sql(self, statement):
        self.statements.append(statement)
        if statement == self.failing:
            raise RuntimeError(f"cannot run {statement}")
        return self.frames.get(statement, _Frame([], []))


def _run(program: str, spark) -> dict:
    emitted = []
    exec(program, {"spark": spark, "emit": emitted.append})
    (value,) = emitted
    return json.loads(json.dumps(value, default=str))


@weaver_test()
def test_the_spark_program_runs_every_statement_and_limits_the_last_in_fabric():
    frame = _Frame(["n"], [(0,), (1,), (2,), (3,)])
    spark = _Spark(frames={"select n from Sales.Order": frame})

    found = _run(
        _spark_sql_program(["set x = 1", "select n from Sales.Order"], 2),
        spark,
    )

    assert spark.statements == ["set x = 1", "select n from Sales.Order"]
    assert found == {
        "columns": ["n"],
        "rows": [[0], [1]],
        "truncated": True,
        "error": None,
    }


@weaver_test()
def test_the_spark_program_reports_a_failure_instead_of_raising():
    found = _run(
        _spark_sql_program(["select boom"], 5),
        _Spark(failing="select boom"),
    )

    assert "cannot run select boom" in found["error"]


@weaver_test()
def test_spark_sql_runs_with_the_lakehouse_attached(session):
    session.answer_python(
        {"columns": ["n"], "rows": [[1]], "truncated": False, "error": None}
    )

    result = weaver.execute(
        "spark-sql",
        "Lakehouse/Landing",
        "set x = 1; select n from Sales.Order",
        session=session,
    )

    (call,) = _calls(session, "python")
    assert call.detail == {"lakehouse": "Landing_Dev", "name": "execute.spark_sql"}
    assert "'select n from Sales.Order'" in call.body
    assert result.result_sets == (ResultSet(columns=("n",), rows=((1,),)),)


@weaver_test()
def test_a_spark_sql_failure_carries_the_trace(session):
    session.answer_python(
        {"columns": [], "rows": [], "truncated": False, "error": "AnalysisException"}
    )

    with pytest.raises(ExecuteError, match="AnalysisException"):
        weaver.execute("spark-sql", "Lakehouse/Landing", "select 1", session=session)


# --- Python --------------------------------------------------------------------


@weaver_test()
def test_the_python_program_returns_what_it_printed():
    found = _run(
        _python_program("print(spark.sql('select 1').columns)", 1000),
        _Spark(frames={"select 1": _Frame(["one"], [])}),
    )

    assert found == {"output": "['one']\n", "truncated": False, "error": None}


@weaver_test()
def test_the_python_program_keeps_output_printed_before_a_failure():
    found = _run(
        _python_program("print('started')\n1 / 0", 1000),
        _Spark(),
    )

    assert found["output"] == "started\n"
    assert "ZeroDivisionError" in found["error"]


@weaver_test()
def test_the_python_program_truncates_long_output():
    found = _run(_python_program("print('x' * 50)", 10), _Spark())

    assert found["output"] == "x" * 10
    assert found["truncated"]


@weaver_test()
def test_python_runs_in_fabric_from_a_file(session, tmp_path):
    path = tmp_path / "investigate.py"
    path.write_text("print('rows')\n", encoding="utf-8")
    session.answer_python({"output": "rows\n", "truncated": False, "error": None})

    result = weaver.execute("python", "Lakehouse/Landing", file=path, session=session)

    (call,) = _calls(session, "python")
    assert "print('rows')" in call.body
    assert call.detail["lakehouse"] == "Landing_Dev"
    assert result.output == "rows\n"
    assert result.result_sets == ()


@weaver_test()
def test_a_python_failure_shows_what_it_printed_first(session):
    session.answer_python(
        {"output": "started\n", "truncated": False, "error": "ZeroDivisionError"}
    )

    with pytest.raises(ExecuteError, match="(?s)started.*ZeroDivisionError"):
        weaver.execute("python", "Lakehouse/Landing", "1 / 0", session=session)


# --- DAX -----------------------------------------------------------------------


class _Model:
    def __init__(self, rows=None, error=None):
        self.queries = []
        self._rows = rows or []
        self._error = error

    def query_dax(self, query):
        self.queries.append(query)
        if self._error is not None:
            raise self._error
        return self._rows


@weaver_test()
def test_dax_queries_the_configured_model(session):
    model = _Model(rows=[{"[Value]": 1}, {"[Value]": 2}])
    session.answer_semantic_model("Sales Analytics", "Reporting_Dev", model)

    result = weaver.execute(
        "dax",
        "SemanticModel/Reporting",
        'EVALUATE ROW("Value", 1)',
        limit=1,
        session=session,
    )

    assert model.queries == ['EVALUATE ROW("Value", 1)']
    assert result.result_sets == (
        ResultSet(columns=("[Value]",), rows=((1,),), truncated=True),
    )


@weaver_test()
def test_a_dax_failure_says_what_power_bi_reported(session):
    from weaver.fabric.client import FabricError

    session.answer_semantic_model(
        "Sales Analytics", "Reporting_Dev", _Model(error=FabricError("Query (1, 10)"))
    )

    with pytest.raises(ExecuteError, match=r"Query \(1, 10\)"):
        weaver.execute("dax", "SemanticModel/Reporting", "EVALUATE x", session=session)


# --- what it refuses -----------------------------------------------------------


@pytest.mark.parametrize(
    "engine, item, message",
    [
        ("sql", "Warehouse/Curated", "engine must be one of"),
        ("tsql", "Lakehouse/Landing", "tsql runs against a Warehouse/Name"),
        ("spark-sql", "Warehouse/Curated", "against a Lakehouse/Name"),
        ("python", "Curated", "against a Lakehouse/Name"),
        ("dax", "Warehouse/Curated", "against a SemanticModel/Name"),
    ],
)
@weaver_test()
def test_an_engine_runs_against_its_own_kind_of_item(session, engine, item, message):
    with pytest.raises(CommandError, match=message):
        weaver.execute(engine, item, "select 1", session=session)
    assert session.calls == []


@pytest.mark.parametrize(
    "arguments, message",
    [
        ({}, "exactly one of command and file"),
        ({"command": "select 1", "file": "x.sql"}, "exactly one of command and file"),
        ({"command": "   "}, "nothing to execute"),
        ({"file": "missing.sql"}, "File not found"),
        ({"command": "select 1", "limit": 0}, "positive integer"),
        ({"command": "select 1", "limit": True}, "positive integer"),
    ],
)
@weaver_test()
def test_a_source_and_limit_are_required(
    session, tmp_path, monkeypatch, arguments, message
):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(CommandError, match=message):
        weaver.execute("tsql", "Warehouse/Curated", session=session, **arguments)


# --- ownership and recording ---------------------------------------------------


@weaver_test()
def test_no_catalogue_is_needed_and_nothing_is_recorded(session):
    weaver.execute("tsql", "Warehouse/Curated", "select 1", session=session)

    assert WORKSPACE.catalogue is None
    assert [call.kind for call in session.calls] == ["tsql"]


@weaver_test()
def test_inside_a_workflow_execute_borrows_its_session(session):
    with weaver.workflow(session=session):
        weaver.execute("tsql", "Warehouse/Curated", "select 1")

    assert len(_calls(session, "tsql")) == 1
    assert not session.closed


@weaver_test()
def test_standalone_execute_closes_the_session_it_opened(monkeypatch, tmp_path):
    opened = []

    def session_for(workspace, **kwargs):
        opened.append(TestSession(workspace=workspace))
        return opened[-1]

    monkeypatch.setattr("weaver.sessions.host.session_for", session_for)
    monkeypatch.delitem(sys.modules, "notebookutils", raising=False)
    monkeypatch.chdir(tmp_path)

    weaver.execute("tsql", "Warehouse/Curated", "select 1", workspace="Sales Analytics")

    (created,) = opened
    assert _calls(created, "tsql")
    assert created.closed


# --- where the source runs -----------------------------------------------------


@weaver_test()
def test_a_desktop_sends_the_source_to_livy_once_with_the_lakehouse_attached(
    monkeypatch,
):
    from weaver.sessions.console import ConsoleSession

    seen = {}

    class _Scope:
        def require_spark_home(self, lakehouse):
            seen["attached"] = lakehouse

        def livy_run(self, source, **kwargs):
            seen.update(kwargs, source=source)
            return {"output": "", "truncated": False, "error": None}

    session = ConsoleSession(workspace=WORKSPACE)
    monkeypatch.setattr(session, "scope", lambda workspace=None: _Scope())
    monkeypatch.setattr(session, "foreground_livy", lambda scope: "livy")

    session.execute_source("emit(1)", lakehouse="Landing_Dev", name="execute.python")

    assert seen["attached"] == "Landing_Dev"
    assert seen["retry_submission"] is False
    assert seen["livy"] == "livy"


def _notebook(monkeypatch, attached):
    module = types.ModuleType("notebookutils")
    module.runtime = types.SimpleNamespace(
        context={
            "currentWorkspaceName": "Sales Analytics",
            "defaultLakehouseName": attached,
        }
    )
    monkeypatch.setitem(sys.modules, "notebookutils", module)


@weaver_test()
def test_a_notebook_runs_the_source_in_process(monkeypatch):
    from weaver.sessions.notebook import NotebookSession

    _notebook(monkeypatch, "Landing_Dev")
    spark = _Spark(frames={"select n": _Frame(["n"], [(1,), (2,)])})
    session = NotebookSession(workspace=WORKSPACE, spark=spark)

    found = session.execute_source(
        _spark_sql_program(["select n"], 1),
        lakehouse="Landing_Dev",
        name="execute.spark_sql",
    )

    assert found == {"columns": ["n"], "rows": [[1]], "truncated": True, "error": None}


@weaver_test()
def test_a_notebook_attached_elsewhere_refuses_the_source(monkeypatch):
    from weaver.sessions.notebook import NotebookSession

    _notebook(monkeypatch, "Raw")
    session = NotebookSession(workspace=WORKSPACE, spark=_Spark())

    with pytest.raises(CommandError, match="attached to Lakehouse 'Raw'"):
        session.execute_source("emit(1)", lakehouse="Landing_Dev", name="x")


# --- the command line ----------------------------------------------------------


def _parse(*words):
    from weaver_cli.main import build_parser

    return build_parser().parse_args(["execute", *words])


@weaver_test()
def test_the_source_option_leaves_the_subcommand_alone():
    args = _parse("tsql", "Warehouse/Curated", "--command", "select 1")

    assert args.command == "execute"
    assert args.source_text == "select 1"
    assert args.source_file is None


@pytest.mark.parametrize(
    "words",
    [
        ("tsql", "Warehouse/Curated"),
        ("tsql", "Warehouse/Curated", "--command", "x", "--file", "y.sql"),
        ("sql", "Warehouse/Curated", "--command", "x"),
        ("tsql", "Warehouse/Curated", "--command", "x", "--limit", "0"),
    ],
)
@weaver_test()
def test_the_parser_refuses_an_incomplete_command(words, capsys):
    with pytest.raises(SystemExit):
        _parse(*words)


@pytest.fixture
def executed(monkeypatch, desktop_credential):
    seen = {}

    def fake(engine, item, command=None, **kwargs):
        seen.update(engine=engine, item=item, command=command, **kwargs)
        if "error" in seen:
            raise seen["error"]
        return ExecuteResult(
            engine=engine,
            item=item,
            target="Curated_Dev",
            result_sets=(ResultSet(columns=("n",), rows=((1,), (2,)), truncated=True),),
            limit=2,
        )

    monkeypatch.setattr(weaver, "execute", fake)
    return seen


def _main(*words):
    from weaver_cli.main import main

    return main(
        ["execute", *words, "--workspace", "Sales Analytics", "--non-interactive"]
    )


@weaver_test()
def test_the_command_reaches_the_api(executed, capsys):
    status = _main("tsql", "Warehouse/Curated", "--command", "select n", "--limit", "2")

    assert status == 0
    assert (executed["engine"], executed["item"], executed["command"]) == (
        "tsql",
        "Warehouse/Curated",
        "select n",
    )
    assert executed["file"] is None
    assert executed["limit"] == 2
    assert "catalogue" not in executed


@weaver_test()
def test_json_is_the_only_thing_on_stdout(executed, capsys):
    status = _main("tsql", "Warehouse/Curated", "--command", "select n", "--json")

    document = json.loads(capsys.readouterr().out)
    assert status == 0
    assert document["status"] == "succeeded"
    assert document["result_sets"] == [
        {"columns": ["n"], "rows": [[1], [2]], "truncated": True}
    ]


@weaver_test()
def test_a_failure_in_json_is_json_and_exits_one(executed, capsys):
    executed["error"] = ExecuteError("T-SQL failed on Curated_Dev: boom")

    status = _main("tsql", "Warehouse/Curated", "--command", "select n", "--json")

    document = json.loads(capsys.readouterr().out)
    assert status == 1
    assert document == {
        "status": "failed",
        "error": {"message": "T-SQL failed on Curated_Dev: boom"},
    }


@weaver_test()
def test_the_table_says_when_it_stopped_at_the_limit(executed, capsys):
    _main("tsql", "Warehouse/Curated", "--command", "select n")

    out = capsys.readouterr().out
    assert out.splitlines()[:4] == ["n", "-", "1", "2"]
    assert "stopped at --limit 2" in out


@weaver_test()
def test_execute_runs_inside_a_session():
    from weaver_cli.shell import NOT_IN_A_SESSION

    assert "execute" not in NOT_IN_A_SESSION
