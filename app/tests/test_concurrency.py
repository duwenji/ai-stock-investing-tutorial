import threading
import time

from common.concurrency import map_concurrently


def test_map_concurrently_returns_result_per_item():
    result = map_concurrently(["a", "b", "c"], lambda item: item.upper())
    assert result == {"a": "A", "b": "B", "c": "C"}


def test_map_concurrently_captures_exception_without_stopping_others():
    def fn(item):
        if item == "bad":
            raise ValueError("boom")
        return item.upper()

    result = map_concurrently(["good", "bad"], fn)
    assert result["good"] == "GOOD"
    assert isinstance(result["bad"], ValueError)
    assert str(result["bad"]) == "boom"


def test_map_concurrently_returns_empty_dict_for_empty_items():
    assert map_concurrently([], lambda item: item) == {}


def test_map_concurrently_runs_tasks_in_parallel():
    barrier = threading.Barrier(3, timeout=1)

    def fn(item):
        barrier.wait()
        return item

    start = time.monotonic()
    result = map_concurrently([1, 2, 3], fn, max_workers=3)
    elapsed = time.monotonic() - start

    assert result == {1: 1, 2: 2, 3: 3}
    assert elapsed < 1.0
