"""A Console Session owns reusable HTTP connections, one request at a time each."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from support.weaver_test import weaver_test

from weaver.sessions import ConsoleSession
from weaver.workspaces import Workspace


@weaver_test()
def test_rest_and_onelake_reuse_http_until_the_owning_session_closes(monkeypatch):
    wires = []

    class Wire:
        def __init__(self):
            self.closed = False
            self.cookies = SimpleNamespace(clear=lambda: None)
            wires.append(self)

        def request(self, method, url, **options):
            return SimpleNamespace(status_code=200, content=b"{}", headers={})

        def close(self):
            self.closed = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    monkeypatch.setattr("requests.Session", Wire)
    monkeypatch.setattr("requests.sessions.Session", Wire)
    credential = SimpleNamespace(
        get_token=lambda scope: SimpleNamespace(token="test", expires_on=1e12)
    )
    with ConsoleSession(credential=credential) as session:
        a = session.scope(Workspace(workspace="A", catalogue="Warehouse/Catalogue"))
        b = session.scope(Workspace(workspace="B", catalogue="Warehouse/Catalogue"))
        a._fabric_client().request("GET", "test")
        b._fabric_client().request("GET", "test")
        a.transport_store._request(
            "GET", "https://onelake.dfs.fabric.microsoft.com/test"
        )
        assert len(wires) == 1
        assert not wires[0].closed
    assert wires[0].closed


@weaver_test()
def test_reused_connections_do_not_carry_response_cookies_into_another_request(
    monkeypatch,
):
    from weaver.fabric.http import HttpTransport

    class Wire:
        def __init__(self):
            self.cookies = {}

        def request(self, method, url, **options):
            assert not self.cookies
            self.cookies["previous-response"] = "not-authentication"

        def close(self):
            pass

    monkeypatch.setattr("requests.Session", Wire)
    transport = HttpTransport()
    try:
        transport.request("GET", "https://api.fabric.microsoft.com/a")
        transport.request("GET", "https://api.fabric.microsoft.com/b")
    finally:
        transport.close()


@weaver_test()
def test_http_sessions_serve_one_request_at_a_time_and_are_session_owned(
    monkeypatch,
):
    from weaver.fabric.http import HttpTransport

    barrier = threading.Barrier(4)

    class Wire:
        def __init__(self):
            self.cookies = {}
            self.closed = False
            self.busy = False

        def request(self, *args, **kwargs):
            assert not self.busy
            self.busy = True
            try:
                barrier.wait(timeout=5)
            finally:
                self.busy = False
            return self

        def close(self):
            self.closed = True

    monkeypatch.setattr("requests.Session", Wire)
    first, second = HttpTransport(), HttpTransport()

    with ThreadPoolExecutor(max_workers=4) as pool:
        owned = set(
            pool.map(lambda _: first.request("GET", "https://example.test"), range(4))
        )
    assert len(owned) == 4
    barrier = threading.Barrier(1)
    other = second.request("GET", "https://example.test")
    assert other not in owned
    first.close()
    assert all(wire.closed for wire in owned)
    assert not other.closed
    second.close()
    assert other.closed
    with pytest.raises(RuntimeError, match="closed"):
        first.request("GET", "https://example.test/c")


@weaver_test()
def test_short_lived_worker_pools_reuse_idle_http_sessions(monkeypatch):
    from weaver.fabric.http import HttpTransport

    wires = []

    class Wire:
        def __init__(self):
            self.cookies = {}
            wires.append(self)

        def request(self, *args, **kwargs):
            return self

        def close(self):
            pass

    monkeypatch.setattr("requests.Session", Wire)
    transport = HttpTransport()
    try:
        for _ in range(20):
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(
                    pool.map(
                        lambda _: transport.request("GET", "https://example.test"),
                        range(4),
                    )
                )
    finally:
        transport.close()
    assert len(wires) <= 4


@weaver_test()
def test_http_close_drains_admitted_requests_before_closing_connections(monkeypatch):
    from weaver.fabric.http import HttpTransport

    started, release, closed = threading.Event(), threading.Event(), threading.Event()

    class Wire:
        def __init__(self):
            self.cookies = {}

        def request(self, *args, **kwargs):
            started.set()
            assert release.wait(timeout=5)
            assert not closed.is_set()

        def close(self):
            closed.set()

    monkeypatch.setattr("requests.Session", Wire)
    transport = HttpTransport()
    with ThreadPoolExecutor(max_workers=2) as pool:
        request = pool.submit(transport.request, "GET", "https://example.test")
        assert started.wait(timeout=5)
        closing = pool.submit(transport.close)
        try:
            assert not closed.wait(timeout=0.1)
        finally:
            release.set()
            closing.result(timeout=5)
        request.result(timeout=5)
    assert closed.is_set()
    with pytest.raises(RuntimeError, match="closed"):
        transport.request("GET", "https://example.test")


@weaver_test()
def test_http_close_attempts_every_connection_and_retains_failures_for_retry(
    monkeypatch,
):
    from weaver.fabric.http import HttpTransport

    wires = []
    barrier = threading.Barrier(2)

    class Wire:
        def __init__(self):
            self.cookies = {}
            self.closed = False
            self.attempts = 0
            wires.append(self)

        def request(self, *args, **kwargs):
            barrier.wait(timeout=5)

        def close(self):
            self.attempts += 1
            if self is wires[0] and self.attempts == 1:
                raise OSError("close failed")
            self.closed = True

    monkeypatch.setattr("requests.Session", Wire)
    transport = HttpTransport()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(
                lambda _: transport.request("GET", "https://example.test"), range(2)
            )
        )
    with pytest.raises(OSError, match="close failed"):
        transport.close()
    assert wires[1].closed
    transport.close()
    assert wires[0].closed
    assert [wire.attempts for wire in wires] == [2, 1]
