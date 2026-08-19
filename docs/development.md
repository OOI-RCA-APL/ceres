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

| Target               | Description                                                     |
| -------------------- | --------------------------------------------------------------- |
| `make install`       | Install Python and console dependencies.                         |
| `make test`          | Run the test suite with pytest.                                  |
| `make test-postgres` | Run the same suite against a real PostgreSQL server.             |
| `make lint`          | Run ruff and pyright, then rustfmt and clippy over the workspace. |
| `make fix`           | Auto-fix lint issues and reformat code.                          |
| `make coverage`      | Regenerate the coverage tables and badges.                       |
| `make coverage-check` | Verify the recorded coverage still matches the sources.         |
| `make console`       | Rebuild the web console bundle the engine serves.                |
| `make build`         | Build the Python package and console.                            |
| `make release`       | Cut a release from the changelog.                                |
| `make release-check` | Preview everything a release would do, without releasing.        |
| `make build-docs`    | Build documentation with mkdocs.                                 |

## Code Style

- **Formatter/linter:** [Ruff](https://docs.astral.sh/ruff/), line width 100, and
  `rustfmt` with `clippy` at `-D warnings` for the Rust workspace.
- **Type checker:** [Pyright](https://github.com/microsoft/pyright).
- **Test framework:** [pytest](https://docs.pytest.org/) with [pytest-asyncio](https://pytest-asyncio.readthedocs.io/), and `cargo test` for the Rust crates.

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
      app/                  # Operations the native server dispatches into.
      cli/                  # The engine-hosting commands the binary delegates back.
      database/             # Entity definitions and the write path.
      core.pyi              # Generated stubs for the native extension.
  rust/                     # The native workspace, built as one extension module.
    ceres-core/             # The pyo3 bridge, imported as ceres.__internal__.core.
    ceres-cli/              # The `ceres` command line interface.
    ceres-server/           # The HTTP server serving the API and console.
    ceres-database/         # Native database access, the filter compiler included.
    ceres-entities/         # Entity structs and their derived filter schemas.
    ceres-config/           # Project configuration parsing.
    ceres-macros/           # Procedural macros for the native crates.
    ceres-stubs/            # Stub generator for core.pyi.
  console/                  # Nuxt web console (Vue 3, TypeScript).
  docs/                     # mkdocs documentation (this site).
  examples/                 # Example projects.
  tests/                    # Test suite.
  scripts/                  # Utility scripts (coverage, releases, the package index).
```

### Key Modules

- `component.py`: The `Component` class, `ComponentSystem`, and all decorators (`@routine`, `@listener`, `@query`, `@action`, `@sieve`). This is the largest and most important module.
- `engine.py`: The `Engine` class that owns the component tree, database, and server. Handles configuration loading and reconciliation.
- `config.py`: Pydantic models for every section of `ceres.yaml`. Configuration validation and type checking.
- `connection/`: `Connection`, `Source` (TCP, Unix), `Splitter`, and `Buffer` classes.
- `event.py`: `Event` base class and all standard event types.
- `error.py`: `Error` base class (a Pydantic dataclass that inherits from `Exception`) and all error types.
- `__internal__/app/`: the operations the native server dispatches into for anything it cannot serve from the database itself.
- `__internal__/cli/`: the engine-hosting commands, which the native binary delegates back to this interpreter.

### The Native Workspace

The engine's HTTP server, command line interface, filter compiler, and database access
are Rust, built as one extension module imported as `ceres.__internal__.core`. The
`ceres` command is a native binary, and `python -m ceres` execs it so both invocations
serve the same surface. Build it with:

```sh
cd rust && cargo build --release
```

The binary lands at `rust/target/release/ceres`, and finds the project's Python
environment through the interpreter beside it, `VIRTUAL_ENV`, or `CERES_PYTHON`.

### Console

The web console is a [Nuxt](https://nuxt.com) application (Vue 3, TypeScript, Nuxt UI,
Pinia, Tailwind) in the `console/` directory, with its own `Makefile` for installing,
linting, and testing.

The engine serves the console from `ceres/static/console`, which is a build artifact
rather than a committed file. The release workflow builds the bundle once and injects
that one copy into every wheel and the sdist, so every artifact serves an identical
console. `make install` builds one only when the directory is missing, so a fresh clone
works and an existing bundle is never rebuilt behind you. A checkout without a bundle
still runs, serving a placeholder page that names the fix. Rebuild deliberately after
console changes with:

```sh
make console
```

For interactive console work, skip the bundle entirely and run a project with the dev
server, which rebuilds as you edit and serves in place of the built-in console:

```sh
ceres run all --development-source /path/to/ceres
```

`--development-source` works from any installed Ceres and applies to every command, not
just `run`. It builds the checkout's CLI, points the invoking environment at an editable
install of the checkout, and delegates the command to the checkout's binary, so the whole
stack runs from source. Each step announces itself on stderr. The
`CERES_DEVELOPMENT_SOURCE` environment variable provides a standing default the flag
overrides, and the CLI reads a `.env` file from the project directory, so a consumer
project opts in with one line:

```sh
echo 'CERES_DEVELOPMENT_SOURCE=/path/to/ceres' >> .env
```

Delegation rebuilds only the CLI binary, so a change to the extension crates still needs
`make install` in the checkout. `--development-console-port` serves the dev console on
its own port instead, leaving the built-in one where it is.

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

Per-module coverage for both the Python package and the Rust workspace is recorded in
[COVERAGE.md](https://github.com/OOI-RCA-APL/ceres/blob/main/COVERAGE.md). `make coverage`
regenerates it, and CI fails when the recorded tables fall behind the sources.

### Running Against PostgreSQL

The suite runs on SQLite by default, while deployments run on PostgreSQL so SQL that only one
backend accepts can pass every test. `make test-postgres` runs the same tests against a real
PostgreSQL server instead.

It expects a server on `localhost:5432` with the `ceres` role, and a database of its own. Create
that database once, as a superuser, since the `ceres` role cannot create databases:

```sh
psql postgres -c "CREATE DATABASE ceres_test OWNER ceres TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C'"
```

The `C` collation is recommended rather than required. Ceres names its own collation when it orders
text so ordering does not depend on how the database was created, and the harness checks the
collation on startup only to keep the test database representative of the recommended deployment.
`tests/test_ordering.py` pins the promised order.

The database is deliberately separate from the one a local deployment uses because the suite
deletes rows and drops schemas wholesale. Set `CERES_TEST_POSTGRES_URL` to point somewhere else.

Every test gets a private schema so the two runs assert exactly the same things. Two modules are
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

3. Commit and push. A release refuses a dirty tree or an unsynced `main` so the state
   being released is always the state on GitHub.
4. Cut the release:

    ```sh
    make release
    ```

The script retitles the changelog section to the version and date, commits and pushes
that, and creates the GitHub release, which triggers the wheel builds. The wheels and
sdist publish to PyPI as `ceres-engine` and attach to the GitHub release alongside a
generated `ceres` alias wheel that pins the release, and when the workflow finishes,
the Pages site redeploys so its package index serves both names. Nothing rewrites the
notes along the way, what the file says is what the release says.

Publishing a GitHub release is the only trigger. Pushing to `main` runs ordinary CI and
never builds wheels or publishes, and neither does pushing a tag by hand. The release
pipeline also reruns the full CI checks itself before building so the released commit is
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

The published site at <https://ooi-rca-apl.github.io/ceres/> deploys through the
`pages` workflow, which also regenerates the package index under `/simple/` from the
release assets. It runs on every push to `main`, after a successful release, and on
manual dispatch so the published docs track the code and the index tracks releases.
