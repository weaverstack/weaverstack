"""Joined read-only discovery has an explicit bounded worker budget."""

from concurrent.futures import ThreadPoolExecutor

from support.weaver_test import weaver_test

from weaver.operations.joined import concurrently


@weaver_test()
def test_discovery_budget_preserves_order_and_other_operations_default(monkeypatch):
    budgets = []

    def pool(*, max_workers):
        budgets.append(max_workers)
        return ThreadPoolExecutor(max_workers=max_workers)

    monkeypatch.setattr("concurrent.futures.ThreadPoolExecutor", pool)
    assert concurrently(list(range(100)), lambda n: n * 2, workers=64) == list(
        range(0, 200, 2)
    )
    assert concurrently(list(range(20)), lambda n: n) == list(range(20))
    assert budgets == [64, 8]
