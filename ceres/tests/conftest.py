import pytest

from ceres.internal.database import Database


@pytest.fixture(scope="function")
def database() -> Database:
    return Database()
