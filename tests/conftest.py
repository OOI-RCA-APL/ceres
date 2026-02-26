import pytest

from ceres.util import ensure_event_loop

pytest.register_assert_rewrite("tests.testing")


# Install `uvloop` and enable eager task factory for all tests if possible.
@pytest.fixture(scope="session", autouse=True)
def setup() -> None:
    ensure_event_loop()
