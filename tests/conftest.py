from asyncio import AbstractEventLoop
from typing import Iterable

import pytest

# Make sure we can import everything in the root module.
from ceres import *  # noqa: F403
from ceres._internal.util import ensure_event_loop


@pytest.fixture(scope="session")
def event_loop() -> Iterable[AbstractEventLoop]:
    loop = ensure_event_loop()
    yield loop
    loop.close()
