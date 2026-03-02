import pytest

pytest.register_assert_rewrite("tests.testing")


# Use `uvloop` and eager tasks for all tests, if possible.
@pytest.fixture(scope="session", autouse=True)
def setup() -> None:
    from ceres.concurrency import el

    el()
