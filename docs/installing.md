# Installing

## Prerequisites

- [Python 3.14+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

## Creating a Project

Initialize a new project with `uv` and add Ceres as a dependency.

```sh
mkdir my-project && cd my-project
uv init
uv add ceres
```

Activate the virtual environment to make the `ceres` command available.

```sh
source .venv/bin/activate
ceres --version
```

You can also install with `pip` if you prefer.

```sh
pip install ceres
```

Ceres ships pre-built wheels for Linux (x86_64 and aarch64), macOS (Apple Silicon and
Intel), and Windows (x64), for both the standard and free-threaded CPython builds, so
installing never compiles anything. On a platform without a pre-built wheel, the install
falls back to building from source, which requires a [Rust](https://rustup.rs) toolchain,
and the `ceres` command is then available as `python -m ceres`.

## Installing a Specific Version

Constrain the version as you would any dependency. Released versions are listed on
[PyPI](https://pypi.org/project/ceres/) and described in the
[changelog](https://github.com/OOI-RCA-APL/ceres/blob/main/CHANGELOG.md).

```sh
uv add ceres==0.41.0
```
