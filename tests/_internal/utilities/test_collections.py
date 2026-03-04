import asyncio
from asyncio import Future
from typing import Any

import pytest

from ceres._internal.utilities.collections import flatten


@pytest.mark.parametrize(
    ["input", "expected"],
    [
        ([], []),
        ([1], [1]),
        ([1, 2, 3], [1, 2, 3]),
        ([1, 2, [3, 4], 5], [1, 2, 3, 4, 5]),
        (["123", ["456"]], ["123", "456"]),
        ((current for current in [b"123", [b"456"]]), [b"123", b"456"]),
        ([1, 2, [[3, 4]], 5], [1, 2, 3, 4, 5]),
    ],
)
def test_flatten(input: Any, expected: Any):
    assert list(flatten(input)) == expected


async def test_flatten_future():
    future = Future()
    task = asyncio.create_task(asyncio.sleep(0))
    assert list(flatten([future, [task]])) == [future, task]
