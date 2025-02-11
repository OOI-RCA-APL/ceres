from asyncio import AbstractEventLoop
from typing import Iterable

import pytest

pytest.register_assert_rewrite("tests.testing")


@pytest.fixture(scope="session")
def event_loop() -> Iterable[AbstractEventLoop]:
    from ceres._internal.util import ensure_event_loop

    loop = ensure_event_loop()
    try:
        yield loop
    finally:
        loop.close()
