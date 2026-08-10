import os
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import Path

import pytest

pytest.register_assert_rewrite("tests.testing")

SQLITE = "sqlite"
TURSO = "turso"
POSTGRES = "postgres"

DATABASES = (SQLITE, TURSO, POSTGRES)
"""Every backend a test can be run against."""

_active = SQLITE
"""Backend unconfigured databases are currently pointed at."""

_selected: tuple[str, ...] = DATABASES
"""Backends this run is allowed to touch, narrowed by `--database`."""

_postgres_used = False
"""Whether any test claimed a PostgreSQL schema so the run knows what to clean up."""


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--database",
        action="append",
        default=[],
        choices=DATABASES,
        help=(
            "Run against this backend alone, repeatable to name several. Narrows the `databases` "
            "marker as well as the backend unmarked tests use, so a run can be confined to one "
            "backend from the command line."
        ),
    )
    parser.addoption(
        "--postgres-url",
        default=None,
        help=(
            "Server the PostgreSQL tests connect to, overriding the CERES_TEST_POSTGRES_URL "
            "environment variable. Points at a throwaway database, never at real data."
        ),
    )
    parser.addoption(
        "--default-database",
        default=SQLITE,
        choices=DATABASES,
        help=(
            "Backend for tests that carry no `databases` marker, which is most of them. Marked "
            "tests still run against everything they name, so use `--database` to confine a run."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    global _active, _selected

    config.addinivalue_line(
        "markers",
        "databases(*names): run this test once against each named backend, or against every "
        "backend when none are named. Unmarked tests run against the default backend alone.",
    )

    url: str | None = config.getoption("--postgres-url")
    if url is not None:
        from tests import postgres

        postgres.use_url(url)

    _active = config.getoption("--default-database")

    chosen: list[str] = config.getoption("--database")
    if chosen:
        _selected = tuple(chosen)
        # Confining the run also moves the unmarked tests since leaving them on an excluded
        # backend would defeat `--database`.
        if _active not in _selected:
            _active = chosen[0]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Turn a `databases` marker into one run of the test per backend.

    Most tests do not care which backend they are on and run once against the default, which keeps
    a full run to a single pass. The ones that do care because they touch SQL a backend writes its
    own way, ask for the rest by name.
    """
    marker = metafunc.definition.get_closest_marker("databases")
    if marker is None:
        return

    names = tuple(marker.args) or DATABASES
    for name in names:
        if name not in DATABASES:
            raise ValueError(f"unknown database backend {name!r}, expected one of {DATABASES}")

    names = tuple(name for name in names if name in _selected)
    if not names:
        # Every backend this test asked for was excluded from the run so there is nothing to do.
        metafunc.parametrize("database", [], indirect=True)
        return

    metafunc.parametrize("database", names, indirect=True)


@contextmanager
def _pointed_at(name: str, patch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point every unconfigured `Database` at `name` for the duration.

    Redirecting the default rather than the tests themselves means the same assertions run against
    whichever backend is in play, which is the whole point of running them more than once.
    """
    global _active, _postgres_used

    from ceres.database import database as module

    previous = _active
    _active = name

    match name:
        case "sqlite":
            from ceres.config import SQLiteDatabaseConfig

            patch.setattr(module, "default_database_config", SQLiteDatabaseConfig)
        case "turso":
            from ceres.config import TursoDatabaseConfig

            patch.setattr(module, "default_database_config", TursoDatabaseConfig)
        case "postgres":
            from tests import postgres

            postgres.prepare()
            _postgres_used = True
            patch.setattr(module, "default_database_config", postgres.database_config)
        case _:
            raise ValueError(f"unknown database backend {name!r}, expected one of {DATABASES}")

    try:
        yield
    finally:
        _active = previous


@cache
def _unavailable(name: str) -> str | None:
    """Explain why `name` cannot be run here, or return `None` when it can.

    A server nobody has started skips its tests rather than failing them so the suite stays
    usable without a PostgreSQL server. Cached because the answer cannot change during a run
    and reaching a server to find out is not free.

    Turso is compiled into Ceres so it is always available and never skips.
    """
    if name == POSTGRES:
        from tests import postgres

        try:
            postgres.prepare()
        except Exception as error:
            return str(error)

    return None


@pytest.fixture(autouse=True)
def working_directory() -> Iterator[None]:
    """Put back what a command that resolves its config path moves.

    Resolving one changes the working directory to the project's and then replaces
    `os.chdir` with a no-op, which a CLI process wants and a session running
    on afterwards does not. Left alone, every later test and pytest's own reports land
    wherever the last CLI test happened to be.
    """
    original = Path.cwd()
    moved = os.chdir
    try:
        yield
    finally:
        from ceres.__internal__.cli import shared

        shared.chdir(original)
        os.chdir = moved


# Use `uvloop` and eager tasks for all tests, if possible.
@pytest.fixture(scope="session", autouse=True)
def setup() -> None:
    from ceres.concurrency import el

    el()


@pytest.fixture(scope="session", autouse=True)
def database_backend() -> Iterator[None]:
    """Point unconfigured databases at the backend the run asked for."""
    from tests import postgres

    try:
        with pytest.MonkeyPatch.context() as patch, _pointed_at(_active, patch):
            yield
    finally:
        if _postgres_used:
            postgres.drop_schemas()


@pytest.fixture(autouse=True)
def database(request: pytest.FixtureRequest) -> Iterator[str]:
    """Run the requesting test against one named backend.

    Autouse so that it sits in every test's fixture closure, which lets
    `pytest_generate_tests` parametrize it by name. A test without the `databases` marker arrives
    here with no parameter and is left on whatever the run already chose.
    """
    name: str | None = getattr(request, "param", None)
    if name is None:
        yield _active
        return

    reason = _unavailable(name)
    if reason is not None:
        pytest.skip(reason)

    with pytest.MonkeyPatch.context() as patch, _pointed_at(name, patch):
        yield name


@pytest.fixture(autouse=True)
async def release_database_resources(database: str) -> AsyncIterator[None]:
    """Return a test's schemas to the pool once it is over."""
    from tests import postgres

    yield

    if _active == POSTGRES:
        postgres.release_schemas()
