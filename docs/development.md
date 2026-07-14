# Development

This guide covers setting up a development environment for working on Ceres itself.

## Prerequisites

- [Git](https://git-scm.com)
- [Make](https://www.gnu.org/software/make)
- [Python 3.14+](https://www.python.org)
- [uv](https://docs.astral.sh/uv)
- [Node.js 24+](https://nodejs.org) (for the web console)

## Setup

1. Clone the repository.

    ```sh
    git clone git@github.com:OOI-RCA-APL/ceres.git
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
    database/               # SQLAlchemy async database layer.
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

## Documentation

Build and preview the documentation locally:

```sh
make build-docs
```

The docs use [mkdocs-material](https://squidfunk.github.io/mkdocs-material/) with [mkdocstrings](https://mkdocstrings.github.io/) for auto-generated API reference.
