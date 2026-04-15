import asyncio

from ceres.channel import Channel, OutputChannel
from ceres.concurrency import sleep, spawn


async def _get_using_reader(stream: OutputChannel[str], count: int) -> list[str]:
    results: list[str] = []
    with stream.read() as values:
        for _ in range(count):
            results.append(await values.get())
        assert len(values) == 0
    return results


async def _get_using_iteration(stream: OutputChannel[str], count: int) -> list[str]:
    results: list[str] = []
    async for value in stream:
        results.append(value)
        if len(results) == count:
            break
    return results


async def test_single_reader() -> None:
    stream = Channel[str]()
    task = asyncio.create_task(_get_using_reader(stream, 3))
    await sleep(0.1)
    stream.put("A")
    stream.put("B")
    stream.put("C")
    assert (await task) == ["A", "B", "C"]
    assert not stream.readers


async def test_multiple_readers() -> None:
    stream = Channel[str]()
    tasks = [asyncio.create_task(_get_using_reader(stream, 3)) for _ in range(10)]
    await sleep(0.1)
    stream.put("A")
    stream.put("B")
    stream.put("C")
    assert (await asyncio.gather(*tasks)) == [["A", "B", "C"]] * 10
    assert not stream.readers


async def test_single_iterator() -> None:
    stream = Channel[str]()
    task = asyncio.create_task(_get_using_iteration(stream, 3))
    await sleep(0.1)
    stream.put("A")
    stream.put("B")
    stream.put("C")
    assert (await task) == ["A", "B", "C"]
    assert not stream.readers


async def test_multiple_iterators() -> None:
    stream = Channel[str]()
    tasks = [asyncio.create_task(_get_using_iteration(stream, 3)) for _ in range(10)]
    await sleep(0.1)
    stream.put("A")
    stream.put("B")
    stream.put("C")
    assert (await asyncio.gather(*tasks)) == [["A", "B", "C"]] * 10
    assert not stream.readers


async def test_clear() -> None:
    stream = Channel[str]()
    with stream.read() as values:
        stream.put("A")
        stream.put("B")
        stream.put("C")
        assert len(values) == 3
        assert values.clear() == ["A", "B", "C"]
        assert len(values) == 0
    assert not stream.readers


async def test_reader_source_is_stream() -> None:
    stream = Channel[str]()
    reader = stream.read()
    assert reader.source is stream


async def test_reader_loop_is_current_loop() -> None:
    stream = Channel[str]()
    reader = stream.read()
    assert reader.loop is asyncio.get_running_loop()


def test_reader_can_be_created_in_sync_code() -> None:
    stream = Channel[str]()
    reader = stream.read()
    assert reader.loop is None

    async def async_code():
        assert reader.loop is None
        stream.put("A")
        # Calling `put` should change the loop to the current loop.
        assert reader.loop is asyncio.get_running_loop()
        assert await reader.get() == "A"

    asyncio.run(async_code())


def test_put_from_sync_code() -> None:
    stream = Channel[str]()
    reader = stream.read()
    stream.put("A")
    assert reader.loop is None

    async def async_code():
        assert reader.loop is None
        assert await reader.get() == "A"
        # Calling `get` should change the loop to the current loop.
        assert reader.loop is asyncio.get_running_loop()

    asyncio.run(async_code())


async def test_write_from_other_thread() -> None:
    stream = Channel[str]()
    reader = stream.read()

    def thread():
        stream.put("A")
        stream.put("B")
        stream.put("C")

    await spawn(thread)
    assert await reader.get() == "A"
    assert await reader.get() == "B"
    assert await reader.get() == "C"


async def test_write_from_other_thread_after_get() -> None:
    stream = Channel[str]()
    reader = stream.read()

    def thread():
        stream.put("A")
        stream.put("B")
        stream.put("C")

    task = asyncio.create_task(spawn(thread))
    assert await reader.get() == "A"
    assert await reader.get() == "B"
    assert await reader.get() == "C"
    await task


async def test_read_from_other_thread() -> None:
    stream = Channel[str]()
    values: list[str] = []
    reader = stream.read()

    def thread():
        async def run():
            values.append(await reader.get())
            values.append(await reader.get())
            values.append(await reader.get())

        asyncio.run(run())

    stream.put("A")
    stream.put("B")
    stream.put("C")
    await spawn(thread)

    assert values == ["A", "B", "C"]
