# Installing

## Prerequisites

- [Python 3.14+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

## Creating A Project

```sh
mkdir my-project && cd my-project
uv init
uv add ceres-engine
```

Activate the virtual environment to make the `ceres` command available.

```sh
source .venv/bin/activate
ceres --version
```

`pip install ceres-engine` works the same way.

The distribution is called `ceres-engine` because the bare name on PyPI belongs to an
unrelated project. It imports as `ceres` regardless, and nothing in your code or
configuration refers to the distribution name.

## Installing From The Project's Own Index

Every release is also published to a package index alongside this documentation, serving
the wheels attached to each
[GitHub release](https://github.com/OOI-RCA-APL/ceres/releases). The bare name is
available there.

```sh
uv add ceres --index https://ooi-rca-apl.github.io/ceres/simple/
```

Record the index in your project to keep using plain `uv add ceres` and `uv sync` without
repeating the flag.

```toml
[[tool.uv.index]]
name = "ceres"
url = "https://ooi-rca-apl.github.io/ceres/simple/"
```

Both names install the same wheels from the same build. Use PyPI unless you have a reason
not to, and this index when you want the bare `ceres` name or are pinned to a deployment
that already resolves against it.

## Wheels And Building From Source

Ceres ships pre-built wheels for Linux (x86_64 and aarch64), macOS (Apple Silicon and
Intel), and Windows (x64), for both the standard and free-threaded CPython builds, so
installing never compiles anything.

On a platform without a pre-built wheel, the install falls back to building from source.
That needs [rustup](https://rustup.rs) and takes a while, but produces the same result,
because the build pins its own toolchain and includes the `ceres` command. `python -m
ceres` runs that command too.

## Installing A Specific Version

Constrain the version as you would any dependency. Released versions are listed on the
[releases page](https://github.com/OOI-RCA-APL/ceres/releases) and described in the
[changelog](https://github.com/OOI-RCA-APL/ceres/blob/main/CHANGELOG.md).

```sh
uv add ceres-engine==<version>
```
