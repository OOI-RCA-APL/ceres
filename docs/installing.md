# Installing

## Prerequisites

- [Python 3.14+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

## Creating a Project

Initialize a new project with `uv` and add Ceres as a dependency from GitHub.

```sh
mkdir my-project && cd my-project
uv init
uv add git+ssh://git@github.com/OOI-RCA-APL/ceres.git
```

Activate the virtual environment to make the `ceres` command available.

```sh
source .venv/bin/activate
ceres --version
```

You can also install with `pip` if you prefer.

```sh
pip install git+ssh://git@github.com/OOI-RCA-APL/ceres.git
```

## Installing a Specific Version

Append `@<version>` to the URL, where `<version>` is a tag from [releases](https://github.com/OOI-RCA-APL/ceres/releases).

```sh
uv add git+ssh://git@github.com/OOI-RCA-APL/ceres.git@0.39.0
```

## GitHub Deploy Keys

When deploying to a server that does not have your personal SSH credentials, you need a [GitHub deploy key](https://docs.github.com/en/rest/deploy-keys/deploy-keys?apiVersion=2022-11-28) for the repository.

1. Generate a key pair on the server.

    ```sh
    ssh-keygen -t ed25519 -f ~/.ssh/ceres-deploy-key -N ""
    ```

2. Add the public key (`~/.ssh/ceres-deploy-key.pub`) to the [OOI-RCA-APL/ceres](https://github.com/OOI-RCA-APL/ceres) repository as a deploy key. If you don't have permissions, send the public key to a repository admin.

3. Configure SSH to use the deploy key for this repository. Add the following to `~/.ssh/config`:

    ```
    Host ceres.github.com
        Hostname github.com
        IdentityFile=~/.ssh/ceres-deploy-key
    ```

4. Tell Git to route requests for this repository through the alias.

    ```sh
    git config --global url.'ssh://git@ceres.github.com/OOI-RCA-APL/ceres.git'.insteadOf \
        'ssh://git@github.com/OOI-RCA-APL/ceres.git'
    ```

After this, `uv add` and `pip install` commands will use the deploy key automatically.
