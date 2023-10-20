| Previous                  | Next                                    |
| ------------------------- | --------------------------------------- |
| [Overview](./overview.md) | [Getting Started](./getting-started.md) |

# Installing

There is no PyPi package for Ceres due to access restrictions, so for now, Ceres must be installed from GitHub.

## Prerequisites

- [Python 3.10+](https://www.python.org/downloads/)
- [Pip](https://pip.pypa.io/en/stable/installing/), [Poetry](https://python-poetry.org/docs/#installation) or another package manager.

## Deploy Keys

_You do not need to do this on a development machine._

If you are deploying Ceres on a server, and don't want to use the GitHub SSH key of a specific user to install it, you'll need to create or request a [GitHub deploy key](https://docs.github.com/en/rest/deploy-keys/deploy-keys?apiVersion=2022-11-28) for the repository.

_Shoot an email to either jploskey@uw.edu or krosburg@uw.edu to request a deploy key if you can't create one yourself._

Once you have a deploy key, you'll need to set up your server to use it. Edit your user's SSH config at `~/.ssh/config` to include the following:

```txt
Host ceres.github.com
        Hostname github.com
        IdentityFile=~/.ssh/<ceres-deploy-key>
```

Then, configure Git to use `ceres.github.com` rather than `github.com` for the Ceres repository:

```sh
git config --global url.'git@ceres.github.com:OOI-RCA-APL/ceres.git'.insteadOf 'git@github.com:OOI-RCA-APL/ceres.git'
```

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
