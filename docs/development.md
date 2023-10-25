# Development

## Dependencies

1. [Git](https://git-scm.com)
2. [Make](https://www.gnu.org/software/make)
3. [Python 3.10+](https://www.python.org)
4. [Poetry](https://python-poetry.org/docs)
5. [NodeJS 16+](https://nodejs.org/en/download)
6. [NPM](https://docs.npmjs.com/downloading-and-installing-node-js-and-npm)

## Setup

1. Clone this repository.
2. Run `make install` at project root.
3. Also in project root, create a directory called `dev`.

   _The `dev` directory is git-ignored._

4. Run `cp -r ./examples/intro dev`.

   _This will create a self-contained example project you can play with._

5. Go into `./dev/intro` and run `poetry install`.

   _This will install local dependencies and create a virtual environment._

6. Run `poetry shell` to enter the project's virtual environment.

   _This makes `ceres` available as a command._

7. Run `ceres run all --watch` to run the project.

   - _The `all` selector makes all components run on engine startup._
   - _The `--watch` flag makes the engine reload when either configuration or code are modified._

8. See the [Getting Started](./getting-started.md) documentation to continue.
