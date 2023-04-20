# Ceres

![CI](https://github.com/OOI-RCA-APL/ceres/actions/workflows/ci.yaml/badge.svg)

## About

Ceres is a Python framework for streaming data collection and monitoring. This project is in active development and is likely to change drastically. No backwards compatibility is guaranteed at this time.

## Development

### Dependencies

1. [Git](https://git-scm.com)
2. [Make](https://www.gnu.org/software/make)
3. [Python 3.10+](https://www.python.org)
4. [Poetry](https://python-poetry.org/docs)
5. [NodeJS 16+](https://nodejs.org/en/download)
6. [NPM](https://docs.npmjs.com/downloading-and-installing-node-js-and-npm)

### Setup

1. Clone this repository.
2. Run `make install` at the root of the project.
3. Also in project root, create a directory called `dev`. The `dev` directory is git-ignored. You can do whatever you want inside of it.
4. Run `cp -r ./examples/crabee dev`. This will create a self-contained example project you can play with inside of the `dev` directory.
5. Go into `./dev/crabee` and run `poetry install`, this will install local dependencies and create a virtual environment.
6. Execute `poetry shell` to enter the virtual environment of the project and make `ceres` available as a command.
7. Execute `ceres run --watch` to run the project and reload when either code or configuration are modified.
8. Go to `localhost:9000`. You should see the web console.
9. Ceres looks for the `ceres.yaml` configuration file in the root of the project in order to function. At the moment, the project is not actually connecting to a real device, only a simulator.

   If you have an actual Crabee device available, edit `ceres.yaml` and change the IP address of the connection component to the IP address of the board.

   ```python3
   - host: 0.0.0.0
   + host: 10.95.96.173
   ```

   Once `ceres.yaml` is saved, the engine should reload immediately.

   If the board is reachable, you should see logs indicating the connection was successful and messages being printed every second, just like the simulator.

   If the board is not reachable, the connection component will attempt to reconnect repeatedly, according to an exponential fallback interval.
