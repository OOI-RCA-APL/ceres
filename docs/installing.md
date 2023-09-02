| Previous                  | Next                                    |
| ------------------------- | --------------------------------------- |
| [Overview](./overview.md) | [Getting Started](./getting-started.md) |

# Installing

## Prerequisites

- [Python 3.10+](https://www.python.org/downloads/)
- [Pip](https://pip.pypa.io/en/stable/installing/), [Poetry](https://python-poetry.org/docs/#installation) or another package manager.

## Pip

To install Ceres globally using Pip, run the following commands.

```sh
pip install git+https://github.com/OOI-RCA-APL/ceres.git#subdirectory=ceres # Install from Github.
ceres --help # The "ceres" command should now be available everywhere.
```

## Poetry

To install Ceres locally in a Poetry project's virtual environment, run the following commands.

```sh
poetry init # Create a Poetry project if it doesn't exist.
poetry add git+https://github.com/OOI-RCA-APL/ceres.git#subdirectory=ceres # Install from Github.
poetry shell # Enter the virtual environment.
ceres --help # The "ceres" command should now be available while in the virtual environment.
```
