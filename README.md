# Ceres

<!-- coverage:badge -->
![Coverage: 87%](https://img.shields.io/badge/coverage-87%25-yellowgreen)
<!-- /coverage:badge -->

A Python framework for building instrument driver systems with real-time data
acquisition, processing, and management.

## Development

Requires Python 3.14+, [uv](https://docs.astral.sh/uv/), and a
[Rust](https://rustup.rs/) toolchain.

```
make install
```

### CLI

The `ceres` command line interface is a native Rust binary living in
[rust/ceres-cli](rust/ceres-cli). Commands that talk to a running engine are handled
natively, while commands that load the engine or operate on the database run in the Python
runtime the binary hands off to. Build it with:

```
cd rust && cargo build --release
```

The binary lands at `rust/target/release/ceres`. It finds the project's Python environment
through the interpreter next to it, `VIRTUAL_ENV`, or the `CERES_PYTHON` environment
variable.

### Testing

```
make test
```

### Coverage

```
make coverage
```

Per-module coverage is tracked in [COVERAGE.md](COVERAGE.md).

### Linting

```
make lint
```

### Formatting

```
make fix
```
