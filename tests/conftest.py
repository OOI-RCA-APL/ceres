import pytest

pytest.register_assert_rewrite("tests.testing")


# Use `uvloop` and eager tasks for all tests, if possible.
@pytest.fixture(scope="session", autouse=True)
def setup() -> None:
    from ceres.concurrency import el

    el()


@pytest.fixture(scope="session", autouse=True)
def database_backend():
    """Point every unconfigured `Database` at PostgreSQL when the run asks for it.

    Redirecting the default rather than the tests themselves means the same assertions run against
    both backends, which is the whole point of the exercise. See `tests.postgres` for how one
    database is kept from seeing another's tables.
    """
    from tests import postgres

    if not postgres.is_enabled():
        yield
        return

    postgres.prepare()

    from ceres.database import database as module

    original = module.default_database_config
    module.default_database_config = postgres.database_config
    try:
        yield
    finally:
        module.default_database_config = original
        postgres.drop_schemas()


@pytest.fixture(autouse=True)
def release_database_schemas():
    """Return the schemas a test claimed once it is over, so later tests can reuse them."""
    from tests import postgres

    yield

    if postgres.is_enabled():
        postgres.release_schemas()
