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

    create_engine = module.Database._create_engine

    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(module, "default_database_config", postgres.database_config)

            # These engines pool their connections, so somebody has to close them. Wrapping engine
            # creation catches every database however a test builds it, including the ones that
            # pass a config of their own and so never reach `default_database_config`.
            patch.setattr(
                module.Database,
                "_create_engine",
                lambda self: postgres.track_engine(create_engine(self)),
            )

            yield
    finally:
        postgres.drop_schemas()


@pytest.fixture(autouse=True)
async def release_database_resources():
    """Close a test's connections and return its schemas once it is over.

    Closing runs here rather than in a synchronous fixture because the connections belong to the
    test's event loop and have to be closed while it is still running.
    """
    from tests import postgres

    yield

    if postgres.is_enabled():
        await postgres.close_engines()
        postgres.release_schemas()
