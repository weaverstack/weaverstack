"""Discovery workers keep HTTP connections bounded across Session operations."""

import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from pathlib import Path

import pytest
from support.weaver_test import weaver_test

from weaver.operations.joined import concurrently
from weaver.sessions import ConsoleSession, NotebookSession
from weaver.workspaces import Workspace


@weaver_test()
def test_repeated_discovery_reuses_workers_and_drains_before_session_close(monkeypatch):
    wires = []

    class Cookies:
        def clear(self):
            pass

    class Wire:
        def __init__(self):
            self.cookies = Cookies()
            self.closed = False
            wires.append(self)

        def request(self, *args, **kwargs):
            assert not self.closed
            return threading.get_ident()

        def close(self):
            self.closed = True

    monkeypatch.setattr("requests.Session", Wire)
    session = ConsoleSession(progress=False)
    try:
        for _ in range(8):
            barrier = threading.Barrier(4)

            def read(entry):
                barrier.wait(timeout=5)
                return session._http.request("GET", "https://example.invalid/")

            outcomes = concurrently(list(range(4)), read, workers=4, session=session)
            assert all(isinstance(result, int) for result in outcomes)
        assert len(wires) == 4
        assert not any(wire.closed for wire in wires)
    finally:
        session.close()
    assert all(wire.closed for wire in wires)
    with pytest.raises(RuntimeError, match="closed"):
        concurrently([1], lambda x: x, session=session)


@pytest.mark.parametrize("session_type", ["ConsoleSession", "NotebookSession"])
@weaver_test()
def test_worker_cannot_close_its_own_session(session_type):
    program = f"""
from weaver.sessions import {session_type}
from weaver.workspaces import Workspace
session = {session_type}(workspace=Workspace(workspace='Example'))
def work(entry):
    try:
        session.close()
    except RuntimeError as error:
        assert 'discovery worker' in str(error)
        return 'rejected'
    raise AssertionError('worker-originated close was allowed')
assert session.map_discovery([0], work, workers=1) == ['rejected']
assert not session.closed
session.close()
assert session.closed
"""
    _assert_program_finishes(program)


def _assert_program_finishes(program):
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / "src"))
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        env=environment,
        timeout=5,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@weaver_test()
def test_worker_close_is_rejected_before_external_console_close_lock():
    _assert_program_finishes("""
import threading
from weaver.sessions import ConsoleSession
session = ConsoleSession(progress=False)
entered = threading.Event()
external_locked = threading.Event()
lock = session._http_close_lock
class ObservedLock:
    def __enter__(self):
        lock.acquire()
        external_locked.set()
    def __exit__(self, *args):
        lock.release()
session._http_close_lock = ObservedLock()
results, errors = [], []
def work(entry):
    entered.set()
    assert external_locked.wait(2)
    try:
        session.close()
    except RuntimeError as error:
        assert 'discovery worker' in str(error)
        return 'rejected'
    raise AssertionError('worker close was allowed')
def discover():
    try:
        results.extend(session.map_discovery([0], work, workers=1))
    except BaseException as error:
        errors.append(error)
def close():
    try:
        session.close()
    except BaseException as error:
        errors.append(error)
coordinator = threading.Thread(target=discover)
coordinator.start()
assert entered.wait(2)
closer = threading.Thread(target=close)
closer.start()
coordinator.join(2)
closer.join(2)
assert not coordinator.is_alive() and not closer.is_alive()
assert not errors, errors
assert results == ['rejected'], results
assert session.closed
""")


@weaver_test()
def test_failed_flusher_close_keeps_discovery_usable_for_retry():
    class Flusher:
        attempts = 0

        def close(self):
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("retryable flush failure")

    session = ConsoleSession(progress=False)
    flusher = Flusher()
    session._flushers["test"] = flusher
    try:
        assert session.map_discovery([1], lambda value: value + 1, workers=1) == [2]
        with pytest.raises(OSError, match="retryable flush failure"):
            session.close()
        assert not session.closed
        assert session.map_discovery([2], lambda value: value + 1, workers=1) == [3]
    finally:
        session.close()
    assert flusher.attempts == 2
    assert session.closed


@weaver_test()
def test_failed_presenter_stop_does_not_leave_an_open_session_drained(monkeypatch):
    session = ConsoleSession(progress=False)
    attempts = []

    def stop():
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("presenter stop failed")

    monkeypatch.setattr(session, "stop_presenting", stop)
    try:
        with pytest.raises(OSError, match="presenter stop failed"):
            session.close()
        assert not session.closed
        assert session.map_discovery([1], lambda value: value, workers=1) == [1]
    finally:
        session.close()
    assert session.closed


@weaver_test()
def test_close_retry_cannot_reopen_admission_under_another_closer(monkeypatch):
    session = NotebookSession(workspace=Workspace(workspace="Example"))
    resuming = threading.Event()
    allow_resume = threading.Event()
    second_flush = threading.Event()
    allow_success = threading.Event()
    resume = session._discovery.resume_admission

    def blocked_resume():
        resuming.set()
        assert allow_resume.wait(5)
        resume()

    class Flusher:
        attempts = 0

        def close(self):
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("first flush failed")
            second_flush.set()
            assert allow_success.wait(5)

    session._flushers["test"] = Flusher()
    monkeypatch.setattr(session._discovery, "resume_admission", blocked_resume)
    with ThreadPoolExecutor(max_workers=2) as pool:
        try:
            first = pool.submit(session.close)
            assert resuming.wait(2)
            second = pool.submit(session.close)
            # A serial closer waits for retry rollback; the broken path enters
            # the second flush before the first closer reopens admission.
            second_flush.wait(0.1)
            allow_resume.set()
            with pytest.raises(OSError, match="first flush failed"):
                first.result(timeout=2)
            assert second_flush.wait(2)
            with pytest.raises(RuntimeError, match="closed"):
                session.map_discovery([0], lambda value: value, workers=1)
        finally:
            allow_resume.set()
            allow_success.set()
        second.result(timeout=2)
    assert session.closed


@pytest.mark.parametrize("workers", [0, -1, 65, True, "4"])
@weaver_test()
def test_discovery_rejects_invalid_worker_budgets(workers):
    with ConsoleSession(progress=False) as session:
        with pytest.raises(ValueError, match="discovery workers"):
            session.map_discovery([0], lambda value: value, workers=workers)


@weaver_test()
def test_reused_discovery_workers_take_each_callers_context():
    value = ContextVar("discovery-value")
    token = value.set("first")
    try:
        with ConsoleSession(progress=False) as session:
            assert (
                session.map_discovery(range(8), lambda _: value.get(), workers=2)
                == ["first"] * 8
            )
            value.set("second")
            assert (
                session.map_discovery(range(8), lambda _: value.get(), workers=2)
                == ["second"] * 8
            )
    finally:
        value.reset(token)


@weaver_test()
def test_discovery_exception_drains_active_work_before_returning():
    barrier = threading.Barrier(2)
    failed = threading.Event()
    release = threading.Event()

    def work(value):
        barrier.wait(timeout=2)
        if value == 0:
            failed.set()
            raise ValueError("expected work failure")
        assert release.wait(2)
        return value

    with (
        ConsoleSession(progress=False) as session,
        ThreadPoolExecutor(max_workers=1) as coordinator,
    ):
        future = coordinator.submit(session.map_discovery, [0, 1], work, workers=2)
        try:
            assert failed.wait(2)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.05)
        finally:
            release.set()
        with pytest.raises(ValueError, match="expected work failure"):
            future.result(timeout=2)
        assert session.map_discovery([3], lambda value: value, workers=1) == [3]
