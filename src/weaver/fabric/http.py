"""Session-owned HTTP connections, each used by one request at a time."""

from __future__ import annotations

import threading


class HttpTransport:
    """Pooled ``requests`` sessions, lent to one request at a time.

    Lending rather than binding a session to its thread keeps the count at the
    peak concurrency: short-lived worker pools reuse idle sessions instead of
    leaving one open per finished thread until the owning Session closes.
    """

    def __init__(self) -> None:
        self._lock = threading.Condition()
        self._close_lock = threading.RLock()
        self._active = 0
        self._sessions = []
        self._idle = []
        self._closed = False

    def request(self, method, url, **options):
        with self._lock:
            if self._closed:
                raise RuntimeError("HTTP transport is closed")
            if self._idle:
                session = self._idle.pop()
            else:
                import requests

                session = requests.Session()
                self._sessions.append(session)
            self._active += 1
        try:
            return session.request(method, url, **options)
        finally:
            # Authentication is supplied per request, not carried by cookies.
            try:
                session.cookies.clear()
            finally:
                with self._lock:
                    self._idle.append(session)
                    self._active -= 1
                    self._lock.notify_all()

    def close(self) -> None:
        with self._close_lock:
            with self._lock:
                self._closed = True
                while self._active:
                    self._lock.wait()
                sessions, self._sessions, self._idle = self._sessions, [], []
            errors = []
            for session in sessions:
                try:
                    session.close()
                except Exception as error:
                    self._sessions.append(session)
                    errors.append(error)
            if errors:
                raise errors[0]
