import pytest

from ceres.database import Database


@pytest.fixture(scope="function")
def database() -> Database:
    return Database()
