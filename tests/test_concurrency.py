import asyncio
import time
from datetime import timedelta

import pytest

from ceres.concurrency import awaitify, azip, cancel, concurrently, el, race, sleep, spawn


async def test_sleep_with_seconds() -> None:
    duration = 0.1
    start = time.monotonic()
    await sleep(duration)
    elapsed = time.monotonic() - start
    assert elapsed >= duration


async def test_sleep_with_timedelta() -> None:
    duration = timedelta(milliseconds=100)
    start = time.monotonic()
    await sleep(duration)
    elapsed = time.monotonic() - start
    assert elapsed >= duration.total_seconds()


async def test_sleep_with_ellipsis_can_be_cancelled() -> None:
    task = asyncio.create_task(sleep(...))
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_awaitify_plain_value() -> None:
    result = await awaitify(42)
    assert result == 42


async def test_awaitify_string() -> None:
    result = await awaitify("hello")
    assert result == "hello"


async def test_awaitify_none() -> None:
    result = await awaitify(None)
    assert result is None


async def test_awaitify_coroutine() -> None:
    async def produce() -> int:
        return 99

    result = await awaitify(produce())
    assert result == 99


async def test_cancel_single_task() -> None:
    task = asyncio.create_task(sleep(...))
    cancelled = await cancel(task)
    assert len(cancelled) == 1
    assert cancelled[0] is task
    assert task.cancelled()


async def test_cancel_multiple_tasks() -> None:
    tasks = [asyncio.create_task(sleep(...)) for _ in range(5)]
    cancelled = await cancel(*tasks)
    assert len(cancelled) == 5
    for task in tasks:
        assert task.cancelled()


async def test_cancel_nested_iterables() -> None:
    group_a = [asyncio.create_task(sleep(...)) for _ in range(3)]
    group_b = [asyncio.create_task(sleep(...)) for _ in range(2)]
    cancelled = await cancel(group_a, group_b)
    assert len(cancelled) == 5
    for task in group_a + group_b:
        assert task.cancelled()


async def test_cancel_already_finished_task() -> None:
    async def immediate() -> int:
        return 1

    task = asyncio.create_task(immediate())
    await task
    cancelled = await cancel(task)
    assert len(cancelled) == 1
    assert not task.cancelled()
    assert task.done()


async def test_cancel_suppresses_exceptions() -> None:
    async def explode() -> None:
        raise ValueError("boom")

    task = asyncio.create_task(explode())
    # Let the task fail before cancelling.
    await asyncio.sleep(0.01)
    cancelled = await cancel(task)
    assert len(cancelled) == 1


async def test_concurrently_runs_all() -> None:
    results: list[int] = []

    async def append(value: int) -> None:
        results.append(value)

    tasks = await concurrently(append(1), append(2), append(3))
    assert len(tasks) == 3
    assert sorted(results) == [1, 2, 3]


async def test_concurrently_skips_none() -> None:
    results: list[int] = []

    async def append(value: int) -> None:
        results.append(value)

    tasks = await concurrently(append(1), None, append(3), None)
    assert len(tasks) == 2
    assert sorted(results) == [1, 3]


async def test_concurrently_accepts_nested_iterables() -> None:
    results: list[int] = []

    async def append(value: int) -> None:
        results.append(value)

    batch = [append(10), append(20)]
    tasks = await concurrently(append(1), batch)
    assert len(tasks) == 3
    assert sorted(results) == [1, 10, 20]


async def test_concurrently_propagates_exception() -> None:
    async def explode() -> None:
        raise ValueError("boom")

    with pytest.raises(ExceptionGroup):
        await concurrently(explode())


async def test_race_returns_first_completed() -> None:
    async def fast() -> str:
        return "fast"

    async def slow() -> str:
        await sleep(10)
        return "slow"

    done, pending = await race(asyncio.create_task(fast()), asyncio.create_task(slow()))
    assert len(done) >= 1
    results = [task.result() for task in done if not task.cancelled()]
    assert "fast" in results
    for task in pending:
        assert task.cancelled()


async def test_race_cancels_pending_by_default() -> None:
    async def fast() -> str:
        return "fast"

    slow_task = asyncio.create_task(sleep(...))
    done, pending = await race(asyncio.create_task(fast()), slow_task)
    assert len(done) >= 1
    assert slow_task.cancelled()


async def test_race_keeps_pending_when_cancel_is_false() -> None:
    async def fast() -> str:
        return "fast"

    slow_task = asyncio.create_task(sleep(...))
    done, pending = await race(
        asyncio.create_task(fast()),
        slow_task,
        cancel=False,
    )
    assert len(done) >= 1
    assert not slow_task.cancelled()
    assert not slow_task.done()
    slow_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await slow_task


async def test_race_accepts_coroutines() -> None:
    async def immediate() -> int:
        return 42

    done, pending = await race(immediate())
    assert len(done) == 1
    completed_task = next(iter(done))
    assert completed_task.result() == 42


async def test_race_raises_exception_by_default() -> None:
    async def explode() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await race(asyncio.create_task(explode()))


async def test_race_suppresses_exception_when_disabled() -> None:
    async def explode() -> None:
        raise ValueError("boom")

    done, pending = await race(asyncio.create_task(explode()), raise_exceptions=False)
    assert len(done) == 1


def test_el_returns_event_loop() -> None:
    loop = el(uvloop=False, eager=False)
    assert isinstance(loop, asyncio.AbstractEventLoop)


async def test_el_returns_running_loop() -> None:
    loop = el()
    running = asyncio.get_running_loop()
    assert loop is running


def test_el_with_eager_sets_task_factory() -> None:
    loop = el(uvloop=False, eager=True)
    assert loop.get_task_factory() is asyncio.eager_task_factory


async def test_spawn_runs_sync_function_in_thread() -> None:
    def add(left: int, right: int) -> int:
        return left + right

    result = await spawn(add, 3, 4)
    assert result == 7


async def test_spawn_with_kwargs() -> None:
    def greet(name: str, greeting: str = "Hello") -> str:
        return f"{greeting}, {name}!"

    result = await spawn(greet, "World", greeting="Hi")
    assert result == "Hi, World!"


async def test_spawn_runs_in_different_thread() -> None:
    import threading

    main_thread = threading.current_thread()

    def get_thread() -> threading.Thread:
        return threading.current_thread()

    worker_thread = await spawn(get_thread)
    assert worker_thread is not main_thread


async def test_azip_two_streams() -> None:
    gate_a = asyncio.Event()
    gate_b = asyncio.Event()

    async def stream_a():
        yield 1
        gate_a.set()
        await gate_b.wait()
        yield 2

    async def stream_b():
        await gate_a.wait()
        yield "x"
        gate_b.set()

    collected: list[tuple[int, str]] = []
    async with azip(stream_a(), stream_b()) as iterator:
        count = 0
        async for pair in iterator:
            collected.append(pair)
            count += 1
            if count >= 2:
                break

    assert collected[0] == (1, "x")
    assert collected[1] == (2, "x")


async def test_azip_waits_for_all_sources_before_emitting() -> None:
    emitted: list[tuple[int, str]] = []
    ready = asyncio.Event()

    async def delayed_ints():
        await ready.wait()
        yield 10

    async def immediate_strings():
        yield "x"
        ready.set()

    async with azip(delayed_ints(), immediate_strings()) as iterator:
        async for pair in iterator:
            emitted.append(pair)
            break

    assert len(emitted) == 1
    assert emitted[0] == (10, "x")


async def test_azip_cancels_tasks_on_exit() -> None:
    async def infinite():
        counter = 0
        while True:
            yield counter
            counter += 1
            await asyncio.sleep(0)

    async with azip(infinite(), infinite()) as iterator:
        async for pair in iterator:
            break

    # If we get here without hanging, the tasks were cancelled properly.


async def test_azip_three_streams() -> None:
    gate_1 = asyncio.Event()
    gate_2 = asyncio.Event()

    async def ints():
        yield 1
        gate_1.set()
        await gate_2.wait()

    async def strings():
        await gate_1.wait()
        yield "a"
        gate_2.set()

    async def floats():
        await gate_1.wait()
        yield 0.5

    collected: list[tuple[int, str, float]] = []
    async with azip(ints(), strings(), floats()) as iterator:
        async for triple in iterator:
            collected.append(triple)
            break

    assert len(collected) == 1
    assert collected[0][0] == 1
    assert collected[0][1] == "a"
    assert collected[0][2] == 0.5
