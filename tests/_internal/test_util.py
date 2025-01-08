from typing import Any

import pytest


@pytest.mark.parametrize(
    ["input", "expected"],
    [
        ([], []),
        ([1], [1]),
        ([1, 2, 3], [1, 2, 3]),
        ([1, 2, [3, 4], 5], [1, 2, 3, 4, 5]),
        ([1, 2, [[3, 4]], 5], [1, 2, [3, 4], 5]),
    ],
)
def test_flatten(input: Any, expected: Any):
    from ceres._internal.util import flatten

    assert list(flatten(input)) == expected
