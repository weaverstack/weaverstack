"""Session-owned discovery workers, separate from resource-acquisition workers."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
from threading import Condition, local

MAX_WORKERS = 64


class DiscoveryExecutor:
    def __init__(self) -> None:
        self._condition = Condition()
        self._pool = None
        self._active = 0
        self._closed = False
        self._shutdown = False
        self._worker = local()

    def assert_can_close(self) -> None:
        if getattr(self._worker, "active", False):
            raise RuntimeError("Cannot close a Session from its discovery worker")

    def _run(self, work, value):
        previous = getattr(self._worker, "active", False)
        self._worker.active = True
        try:
            return work(value)
        finally:
            self._worker.active = previous

    def map(self, entries, work, *, workers):
        if type(workers) is not int or not 1 <= workers <= MAX_WORKERS:
            raise ValueError(f"discovery workers must be from 1 to {MAX_WORKERS}")
        values = tuple(entries)
        with self._condition:
            if self._closed:
                raise RuntimeError("Discovery executor is closed")
            if not values:
                return []
            if self._pool is None:
                self._pool = ThreadPoolExecutor(
                    max_workers=MAX_WORKERS, thread_name_prefix="weaver-discovery"
                )
            pool = self._pool
            self._active += 1
        pending = {}
        remaining = iter(enumerate(values))
        results = [None] * len(values)

        def submit():
            entry = next(remaining, None)
            if entry is not None:
                index, value = entry
                pending[pool.submit(copy_context().run, self._run, work, value)] = index

        try:
            for _ in range(min(workers, len(values))):
                submit()
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    index = pending.pop(future)
                    results[index] = future.result()
                for _ in done:
                    submit()
            return results
        finally:
            for future in pending:
                future.cancel()
            if pending:
                wait(pending)
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def drain(self) -> None:
        """Reject new batches and drain existing ones without retiring workers."""

        self.assert_can_close()
        with self._condition:
            self._closed = True
            while self._active:
                self._condition.wait()

    def resume_admission(self) -> None:
        """Keep an open Session usable after its logging barrier fails."""

        with self._condition:
            if self._shutdown:
                raise RuntimeError("Discovery executor has shut down")
            self._closed = False

    def close(self) -> None:
        self.drain()
        with self._condition:
            self._shutdown = True
            pool = self._pool
        if pool is not None:
            pool.shutdown(wait=True)
