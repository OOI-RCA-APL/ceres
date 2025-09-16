# Development

## Dependencies

- [Git](https://git-scm.com)
- [Make](https://www.gnu.org/software/make)
- [Python 3.12+](https://www.python.org)
- [UV](https://github.com/astral-sh/uv)
- [NodeJS 24+](https://nodejs.org/en/download)

## Setup

1. Clone this repository.
2. Run `make install` at project root.
3. Also in project root, create a directory called `dev`. _This directory is git-ignored._
4. Run `cp -r ./examples/intro dev`. _This will create a self-contained example project you can play with._
5. Go into `./dev/intro` and run `uv sync`. _This will install local dependencies and create a virtual environment._
6. Run `source ./.venv/bin/activate` to enter the project's virtual environment. _This makes `ceres` available as a command._
7. Run `ceres run all --watch` to run the project. _The `all` selector makes all components run on engine startup, and
   the `--watch` option makes the engine reload when configuration and/or code are modified._
