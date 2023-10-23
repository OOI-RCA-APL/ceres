from asyncio import AbstractEventLoop
from typing import Iterable

import pytest

from ceres.internal.utilities import ensure_event_loop


@pytest.fixture(scope="session")
def event_loop() -> Iterable[AbstractEventLoop]:
    loop = ensure_event_loop()
    yield loop
    loop.close()
