"""A Console Session owns reusable, thread-confined HTTP connections."""

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
def test_http_pool_is_thread_confined_and_session_owned(monkeypatch):
    from weaver.fabric.http import HttpTransport

    wires = []
    barrier = threading.Barrier(4)

    class Wire:
        def __init__(self):
            self.owner = threading.get_ident()
            self.cookies = {}
            self.closed = False
            wires.append(self)

        def request(self, *args, **kwargs):
            assert self.owner == threading.get_ident()
            return self

        def close(self):
            self.closed = True

    monkeypatch.setattr("requests.Session", Wire)
    first, second = HttpTransport(), HttpTransport()

    def worker(_):
        barrier.wait(timeout=5)
        a = first.request("GET", "https://example.test/a")
        assert first.request("GET", "https://example.test/b") is a
        assert second.request("GET", "https://example.test/a") is not a
        return a

    with ThreadPoolExecutor(max_workers=4) as pool:
        owned = list(pool.map(worker, range(4)))
    assert len(wires) == 8
    first.close()
    assert all(wire.closed for wire in owned)
    assert all(not wire.closed for wire in wires if wire not in owned)
    second.close()
    assert all(wire.closed for wire in wires)
    with pytest.raises(RuntimeError, match="closed"):
        first.request("GET", "https://example.test/c")


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
