"""Session-owned HTTP connections, confined to the thread using them."""

from __future__ import annotations

import threading


class HttpTransport:
    def __init__(self) -> None:
        self._local = threading.local()
        self._lock = threading.Condition()
        self._close_lock = threading.RLock()
        self._active = 0
        self._sessions = []
        self._closed = False

    def request(self, method, url, **options):
        with self._lock:
            if self._closed:
                raise RuntimeError("HTTP transport is closed")
            session = getattr(self._local, "session", None)
            if session is None:
                import requests

                session = requests.Session()
                self._local.session = session
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
                    self._active -= 1
                    self._lock.notify_all()

    def close(self) -> None:
        with self._close_lock:
            with self._lock:
                self._closed = True
                while self._active:
                    self._lock.wait()
                sessions, self._sessions = self._sessions, []
            errors = []
            for session in sessions:
                try:
                    session.close()
                except Exception as error:
                    self._sessions.append(session)
                    errors.append(error)
            if errors:
                raise errors[0]
