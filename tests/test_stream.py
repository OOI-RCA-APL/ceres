import asyncio

from ceres.stream import Stream, WriteStream


async def _get_using_reader(stream: Stream[str], count: int) -> list[str]:
    results: list[str] = []
    with stream.read() as values:
        for _ in range(count):
            results.append(await values.get())
        assert len(values) == 0
    return results


async def _get_using_iteration(stream: Stream[str], count: int) -> list[str]:
    results: list[str] = []
    async for value in stream:
        results.append(value)
        if len(results) == count:
            break
    return results


async def test_single_reader() -> None:
    stream = WriteStream[str]()
    task = asyncio.create_task(_get_using_reader(stream, 3))
    await asyncio.sleep(0.1)
    stream.put("A")
    stream.put("B")
    stream.put("C")
    assert (await task) == ["A", "B", "C"]
    assert not stream.readers


async def test_multiple_readers() -> None:
    stream = WriteStream[str]()
    tasks = [asyncio.create_task(_get_using_reader(stream, 3)) for _ in range(10)]
    await asyncio.sleep(0.1)
    stream.put("A")
    stream.put("B")
    stream.put("C")
    assert (await asyncio.gather(*tasks)) == [["A", "B", "C"]] * 10
    assert not stream.readers


async def test_single_iterator() -> None:
    stream = WriteStream[str]()
    task = asyncio.create_task(_get_using_iteration(stream, 3))
    await asyncio.sleep(0.1)
    stream.put("A")
    stream.put("B")
    stream.put("C")
    assert (await task) == ["A", "B", "C"]
    assert not stream.readers


async def test_multiple_iterators() -> None:
    stream = WriteStream[str]()
    tasks = [asyncio.create_task(_get_using_iteration(stream, 3)) for _ in range(10)]
    await asyncio.sleep(0.1)
    stream.put("A")
    stream.put("B")
    stream.put("C")
    assert (await asyncio.gather(*tasks)) == [["A", "B", "C"]] * 10
    assert not stream.readers


async def test_clear() -> None:
    stream = WriteStream[str]()
    with stream.read() as values:
        stream.put("A")
        stream.put("B")
        stream.put("C")
        assert len(values) == 3
        assert values.clear() == ["A", "B", "C"]
        assert len(values) == 0
    assert not stream.readers
