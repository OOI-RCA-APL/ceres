import asyncio

from ceres.stream import Stream


async def test_single_consumer() -> None:
    stream: Stream[str] = Stream()

    async def get() -> list[str]:
        results: list[str] = []
        with stream.read() as values:
            for _ in range(3):
                results.append(await values.get())
            assert len(values) == 0
        return results

    task = asyncio.create_task(get())
    await asyncio.sleep(0.1)
    stream.put("A")
    stream.put("B")
    stream.put("C")
    assert (await task) == ["A", "B", "C"]
    assert not stream._readers


async def test_iteration() -> None:
    stream: Stream[str] = Stream()

    async def get() -> list[str]:
        results: list[str] = []
        async for value in stream.read():
            results.append(value)
            if len(results) == 3:
                break
        return results

    task = asyncio.create_task(get())
    await asyncio.sleep(0.1)
    stream.put("A")
    stream.put("B")
    stream.put("C")
    assert (await task) == ["A", "B", "C"]


async def test_clear() -> None:
    stream: Stream[str] = Stream()

    with stream.read() as values:
        stream.put("A")
        stream.put("B")
        stream.put("C")
        assert len(values) == 3
        assert values.clear() == ["A", "B", "C"]
        assert len(values) == 0

    assert not stream._readers
