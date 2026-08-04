# Development

This guide covers setting up a development environment for working on Ceres itself.

## Prerequisites

- [Git](https://git-scm.com)
- [Make](https://www.gnu.org/software/make)
- [Python 3.14+](https://www.python.org)
- [uv](https://docs.astral.sh/uv)
- [Rust](https://rustup.rs) (nightly, selected automatically by `rust-toolchain.toml`)
- [Node.js 24+](https://nodejs.org) (for the web console)

## Setup

1. Clone the repository.

    ```sh
    git clone https://github.com/OOI-RCA-APL/ceres.git
    cd ceres
    ```

2. Install all dependencies (Python and console).

    ```sh
    make install
    ```

3. Create a local development project. The `dev/` directory is git-ignored.

    ```sh
    mkdir dev
    cp -r examples/counter dev/counter
    cd dev/counter
    uv sync
    source .venv/bin/activate
    ```

4. Run the example project with hot-reload.

    ```sh
    ceres run all --watch
    ```

    This starts the counter example and automatically restarts when you modify Python files or configuration in the Ceres source or the example project.

## Make Targets

| Target          | Description                                      |
| --------------- | ------------------------------------------------ |
| `make install`  | Install Python and console dependencies.         |
| `make test`     | Run the test suite with pytest.                  |
| `make lint`     | Run ruff (check + format) and pyright.           |
| `make fix`      | Auto-fix lint issues and reformat code.          |
| `make coverage` | Generate the coverage report.                    |
| `make build`    | Build the Python package and console.            |
| `make release`  | Cut a release from the changelog.                |
| `make build-docs` | Build documentation with mkdocs.               |

## Code Style

- **Formatter/linter:** [Ruff](https://docs.astral.sh/ruff/), line width 100.
- **Type checker:** [Pyright](https://github.com/microsoft/pyright).
- **Test framework:** [pytest](https://docs.pytest.org/) with [pytest-asyncio](https://pytest-asyncio.readthedocs.io/).

Always run `make lint` before committing. The CI pipeline runs the same checks.

## Project Structure

```
ceres/
  ceres/                    # Main Python package.
    __init__.py             # Public API exports.
    component.py            # Component, routines, listeners, queries, actions.
    engine.py               # Engine orchestration.
    config.py               # Configuration loading and validation.
    connection/             # Connection system (sources, splitters, buffers).
    database/               # Async database layer over the native store.
    error.py                # Error hierarchy.
    event.py                # Event system.
    particle.py             # Data parsing (particles).
    __internal__/
      app/                  # FastAPI HTTP server and REST API.
        api/                # API route modules.
      cli/                  # CLI entry point and subcommands.
      database/             # ORM entity definitions.
  console/                  # Vue 3 + Quasar web console (TypeScript).
  docs/                     # mkdocs documentation (this site).
  examples/                 # Example projects.
  tests/                    # Test suite.
  scripts/                  # Utility scripts (coverage, multi-version testing).
```

### Key Modules

- `component.py`: The `Component` class, `ComponentSystem`, and all decorators (`@routine`, `@listener`, `@query`, `@action`, `@sieve`). This is the largest and most important module.
- `engine.py`: The `Engine` class that owns the component tree, database, and server. Handles configuration loading and reconciliation.
- `config.py`: Pydantic models for every section of `ceres.yaml`. Configuration validation and type checking.
- `connection/`: `Connection`, `Source` (TCP, Unix), `Splitter`, and `Buffer` classes.
- `event.py`: `Event` base class and all standard event types.
- `error.py`: `Error` base class (a Pydantic dataclass that inherits from `Exception`) and all error types.
- `__internal__/app/`: FastAPI application, middleware, and REST API routes.
- `__internal__/cli/`: CLI commands built on pydantic-settings.

### Console

The web console is a separate Vue 3 / TypeScript / Quasar application in the `console/` directory. It has its own `Makefile` and build process. `make install` and `make build` at the project root handle both Python and console dependencies.

## Testing

Run the full test suite:

```sh
make test
```

Run a specific test file or test:

```sh
uv run pytest tests/test_error.py -vv
uv run pytest tests/test_error.py::TestErrorIsException -vv
```

### Running Against PostgreSQL

The suite runs on SQLite by default, while deployments run on PostgreSQL, so SQL that only one
backend accepts can pass every test. `make test-postgres` runs the same tests against a real
PostgreSQL server instead.

It expects a server on `localhost:5432` with the `ceres` role, and a database of its own. Create
that database once, as a superuser, since the `ceres` role cannot create databases:

```sh
psql postgres -c "CREATE DATABASE ceres_test OWNER ceres TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C'"
```

The `C` collation is recommended rather than required. Ceres names its own collation when it orders
text, so ordering does not depend on how the database was created, and the harness checks the
collation on startup only to keep the test database representative of the recommended deployment.
See `2026-07-27-string-ordering-design.md`.

The database is deliberately separate from the one a local deployment uses, because the suite
deletes rows and drops schemas wholesale. Set `CERES_TEST_POSTGRES_URL` to point somewhere else.

Every test gets a private schema, so the two runs assert exactly the same things. Two modules are
backend-specific by nature and stay that way: `tests/test_migrations.py` reads `sqlite_master`, and
`tests/test_migrations_postgres.py` replays the migrations against PostgreSQL on either run.

## Releasing

The "Unreleased" section of `CHANGELOG.md` is the release notes, shipped verbatim, and
`version` in `pyproject.toml` is the version being released. To release:

1. Edit the "Unreleased" section until it reads right. It is an ordinary file change, so
   reword, reorder, and commit as usual.
2. Preview the release:

    ```sh
    make release-check
    ```

    This runs every check a release runs, reporting each problem rather than stopping at
    the first, and shows exactly what a release would do, the `CHANGELOG.md` diff, the
    commit, and the GitHub release title and body.

3. Commit and push. A release refuses a dirty tree or an unsynced `main`, so the state
   being released is always the state on GitHub.
4. Cut the release:

    ```sh
    make release
    ```

The script retitles the changelog section to the version and date, commits and pushes
that, and creates the GitHub release with the entry as its notes, which triggers the
wheel builds and the PyPI publish. Nothing rewrites the notes along the way, what the
file says is what the release says.

Publishing a GitHub release is the only trigger. Pushing to `main` runs ordinary CI and
never builds wheels or publishes, and neither does pushing a tag by hand. The release
pipeline also reruns the full CI checks itself before building, so the released commit is
verified by the pipeline that releases it rather than trusting an earlier run, which
means the checks run twice on release day, once for the push and once as the release
gate. That redundancy is deliberate.

To fix release notes after publishing, edit the changelog entry in a normal commit and
mirror it with `gh release edit <version> --notes-file <file>`. The published release
body is editable without touching the tag or re-triggering the pipeline.

## Documentation

Build and preview the documentation locally:

```sh
make build-docs
```

The docs use [mkdocs-material](https://squidfunk.github.io/mkdocs-material/) with [mkdocstrings](https://mkdocstrings.github.io/) for auto-generated API reference.
