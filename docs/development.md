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

4. Run `cp -r ./examples/crabee dev`.

   _This will create a self-contained example project you can play with._

5. Go into `./dev/crabee` and run `poetry install`.

   _This will install local dependencies and create a virtual environment._

6. Run `poetry shell` to enter the project's virtual environment.

   _This makes `ceres` available as a command._

7. Run `ceres run --all --watch` to run the project.

   - _The `--all` flag starts all components on engine startup._
   - _The `--watch` flag makes the engine reload when either configuration or code are modified._

8. Go to `localhost:9000`. You should see the web console.

9. Ceres reads the `ceres.yaml` configuration file at the project root in order to function. At the moment, the project is not actually connecting to a real device, only a simulator.

If you have an actual Crabee device available, edit `ceres.yaml` and change the IP address of the connection component to the IP address of the board.

```python3
- host: 0.0.0.0
+ host: 10.95.96.173
```

Once `ceres.yaml` is saved, the engine should reload immediately and try to connect to the device.

If the device is reachable, you should see logs indicating the connection was successful and messages should be printed every second, just like the simulator.

If the device is not reachable, the connection component will log errors and attempt to reconnect repeatedly according to an exponential fallback interval.
