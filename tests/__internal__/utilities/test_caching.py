import gc

import pytest

from ceres.__internal__.utilities.caching import LRUCache, cached


def test_cached_zero_arg_caches_result():
    call_count = 0

    @cached
    def compute():
        nonlocal call_count
        call_count += 1
        return 42

    assert compute() == 42
    assert compute() == 42
    assert call_count == 1


def test_cached_single_arg_caches_per_arg():
    call_count = 0

    @cached
    def square(number):
        nonlocal call_count
        call_count += 1
        return number * number

    assert square(3) == 9
    assert square(4) == 16
    assert square(3) == 9
    assert call_count == 2


def test_cached_multi_arg_caches_per_arg_combo():
    call_count = 0

    @cached
    def add(first, second):
        nonlocal call_count
        call_count += 1
        return first + second

    assert add(1, 2) == 3
    assert add(3, 4) == 7
    assert add(1, 2) == 3
    assert call_count == 2


def test_cached_with_custom_storage():
    storage: dict = {}

    @cached(storage=storage)
    def double(number):
        return number * 2

    assert double(5) == 10
    assert 5 in storage


def test_cached_with_weak_true():
    @cached(weak=True)
    def identity(key):
        return id(key)

    class Token:
        pass

    token = Token()
    result = identity(token)
    assert identity(token) == result

    del token
    gc.collect()


def test_cached_with_storage_and_weak_raises():
    with pytest.raises(ValueError, match="Cannot use custom storage with weak-key caching"):
        cached(storage={}, weak=True)


def test_lru_cache_basic_get_set_delete():
    cache: LRUCache[str, int] = LRUCache()
    cache["alpha"] = 1
    assert cache["alpha"] == 1

    del cache["alpha"]
    with pytest.raises(KeyError):
        _ = cache["alpha"]


def test_lru_cache_eviction():
    cache: LRUCache[int, str] = LRUCache(capacity=2, threshold=0.5)
    cache[1] = "a"
    cache[2] = "b"
    cache[3] = "c"
    cache[4] = "d"

    assert len(cache) <= 2 + 2 * 0.5


def test_lru_cache_len_and_iter():
    cache: LRUCache[str, int] = LRUCache()
    cache["x"] = 1
    cache["y"] = 2
    cache["z"] = 3

    assert len(cache) == 3
    assert set(cache) == {"x", "y", "z"}


def test_lru_cache_values():
    cache: LRUCache[str, int] = LRUCache()
    cache["a"] = 10
    cache["b"] = 20

    assert sorted(cache.values()) == [10, 20]


def test_lru_cache_size_threshold():
    cache: LRUCache[str, int] = LRUCache(capacity=100, threshold=0.5)
    assert cache.size_threshold == 150.0

    cache_small: LRUCache[str, int] = LRUCache(capacity=10, threshold=0.25)
    assert cache_small.size_threshold == 12.5


def test_lru_cache_get_with_default():
    cache: LRUCache[str, int] = LRUCache()
    assert cache.get("missing") is None
    assert cache.get("missing", 99) == 99

    cache["present"] = 42
    assert cache.get("present") == 42
    assert cache.get("present", 99) == 42
