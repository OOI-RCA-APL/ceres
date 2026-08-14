# Ceres

<!-- coverage:badge -->
![Python Coverage: 87%](https://img.shields.io/badge/python%20coverage-87%25-yellowgreen)
![Rust Coverage: 74%](https://img.shields.io/badge/rust%20coverage-74%25-yellow)
<!-- /coverage:badge -->

Ceres is a Python framework for building data collection, monitoring, and device control systems. It takes ideas from service management tools like Docker and SystemD, scales them down, and applies them to Python objects called _components_.

Components are async Python classes that run concurrently, communicate through events, and persist their state in a database. They can connect to remote instruments over TCP, parse incoming data into structured records, emit alerts, and be managed through a CLI or web console.

![architecture](https://ooi-rca-apl.github.io/ceres/images/architecture.png)

## Where Ceres Is Used

Ceres was built at the University of Washington Applied Physics Laboratory (APL) to power instrument drivers for the [Ocean Observatories Initiative (OOI)](https://oceanobservatories.org/) Regional Cabled Array (RCA). Ceres runs on Linux, macOS, and Windows. In its current production deployment, it runs on physical Linux servers connected to oceanographic instruments (acoustic current profilers, pressure gauges, pH sensors, etc.), collecting and processing real-time data streams over TCP.

That said, Ceres is a general-purpose framework. It can manage any collection of async Python components that need lifecycle control, event handling, scheduling, and persistence.

## Quick Example

```python
from ceres import Component, routine, sleep


class Counter(Component):
    initial: int
    delta: int = 1

    @routine
    async def count(self) -> None:
        count = self.initial
        while True:
            self.system.log.info(count)
            await sleep(1)
            count += self.delta
```

```yaml
# ceres.yaml
database:
  type: sqlite
  path: ./database.sqlite

components:
  - name: counter-a
    class: counter.Counter
    arguments:
      initial: 5
  - name: counter-b
    class: counter.Counter
    arguments:
      initial: 100
      delta: -5
```

```sh
ceres run all             # Run both components in the foreground.
ceres service start       # Or run as a background service.
ceres status              # Check engine and component states.
ceres start all           # Start all components.
ceres enable all          # Auto-start components on engine startup.
ceres service stop        # Stop the background service.
```

## Documentation

The documentation is published at
[ooi-rca-apl.github.io/ceres](https://ooi-rca-apl.github.io/ceres/).

Start here:

- [Installing](https://ooi-rca-apl.github.io/ceres/installing/): Install Ceres and set up a project.
- [Getting Started](https://ooi-rca-apl.github.io/ceres/getting-started/): Build your first Ceres project from scratch.
- [Components](https://ooi-rca-apl.github.io/ceres/components/): The core abstraction, routines, events, records.
- [Connections](https://ooi-rca-apl.github.io/ceres/connections/): Connect to remote instruments and parse data.
- [Writing a Driver](https://ooi-rca-apl.github.io/ceres/writing-a-driver/): Build an instrument driver end to end.
- [Deployment](https://ooi-rca-apl.github.io/ceres/deployment/): Run Ceres as a production service.

Reference, generated from the code and checked in CI:

- [Configuration](https://ooi-rca-apl.github.io/ceres/reference/configuration/): Every `ceres.yaml` key.
- [CLI](https://ooi-rca-apl.github.io/ceres/reference/cli/): Every command and option.
- [HTTP API](https://ooi-rca-apl.github.io/ceres/reference/http-api/): Every route the engine serves.
- [Python API](https://ooi-rca-apl.github.io/ceres/reference/python-api/): Every name `ceres` exports.

Contributing:

- [Development](https://ooi-rca-apl.github.io/ceres/development/): Set up a dev environment and contribute to Ceres.
