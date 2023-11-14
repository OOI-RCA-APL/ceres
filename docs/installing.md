| Previous                  | Next                                    |
| ------------------------- | --------------------------------------- |
| [README.md](../README.md) | [Getting Started](./getting-started.md) |

# Installing

There is no PyPi package for Ceres due to access restrictions. The package must be installed from GitHub.

## Prerequisites

### Software

- [Python 3.10+](https://www.python.org/downloads/)
- [Pip](https://pip.pypa.io/en/stable/installing/), [Poetry](https://python-poetry.org/docs/#installation) or another package manager.

### GitHub Deploy Key

If you are deploying a Ceres project on a server, you'll need a [GitHub deploy key](https://docs.github.com/en/rest/deploy-keys/deploy-keys?apiVersion=2022-11-28) for this repository.

1. On your server, use `ssh-keygen` to generate a public/private SSH key pair at `~/.ssh/ceres-deploy-key` and `~/.ssh/ceres-deploy-key.pub` respectively.

2. Add the public SSH key to this GitHub repository as a deploy key, if you have permissions. Otherwise, send the public SSH key to either jploskey@uw.edu or krosburg@uw.edu and ask them nicely.

3. Once you have the deploy key, configure your server to use it.

   1. Edit your user's SSH config at `~/.ssh/config` to include:

      ```txt
      Host ceres.github.com
          Hostname github.com
          IdentityFile=~/.ssh/ceres-deploy-key
      ```

   1. Configure Git to use `ceres.github.com` rather than `github.com` for the repository. This will make Git use the deploy key as its SSH authentication method during installation:

      ```sh
      git config --global url.'ssh://git@ceres.github.com/OOI-RCA-APL/ceres.git'.insteadOf 'ssh://git@github.com/OOI-RCA-APL/ceres.git'
      ```

## Install

### Pip

```sh
pip install git+ssh://git@github.com/OOI-RCA-APL/ceres.git # Install latest package from GitHub.
ceres --help # The "ceres" command should now be available everywhere.
```

### Virtual Environment + Pip

```sh
python -m venv .venv # Create a virtual environment.
source .venv/bin/activate # Enter the virtual environment.
pip install git+ssh://git@github.com/OOI-RCA-APL/ceres.git # Install latest package from GitHub.
ceres --help # The "ceres" command should now be available everywhere.
```

### Virtual Environment + Poetry

```sh
poetry init # Create a Poetry project if it doesn't exist.
poetry add git+ssh://git@github.com/OOI-RCA-APL/ceres.git # Install latest package from GitHub.
poetry shell # Enter auto-generated the virtual environment.
ceres --help # The "ceres" command should now be available while in the virtual environment.
```

## Tips

To install a specific version, append "@\<version\>" to the URL, where `<version>` is a tag from [releases](https://github.com/OOI-RCA-APL/ceres/releases).

```
pip install git+ssh://git@github.com/OOI-RCA-APL/ceres.git@<version>
poetry add git+ssh://git@github.com/OOI-RCA-APL/ceres.git@<version>
```
