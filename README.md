# Ceres

![CI](https://github.com/OOI-RCA-APL/ceres/actions/workflows/ci.yaml/badge.svg)

Ceres is a Python framework for data collection, monitoring and device control. Ceres take concepts from tools like Systemd, Docker and Kubernetes, scales them down, and applies them to Python objects called _components_.

![architecture](./docs/images/architecture.png)

| ⚠                                                                                                                                  |
| ---------------------------------------------------------------------------------------------------------------------------------- |
| _This project is in active development and will likely change drastically. No backwards compatibility is guaranteed at this time._ |

## Example

```python
# ./examples/counter/example/counter.py

from asyncio import sleep

from ceres import Component, routine

class Counter(Component):
    # Components are dataclasses, so attributes are per-instance, and can be passed via the
    # component's constructor, or more commonly, through the component's `arguments` configuration
    # in `ceres.yaml` as shown below.
    initial: int
    delta: int = 1

    # Components can declare one or more "routines," which execute concurrently when a component
    # is started, and are cancelled when the component is stopped.
    @routine
    async def count(self) -> None:
        count = self.initial  # Start counting from `initial`.
        while True:
            self.log.info(count)  # Print the current count.
            await sleep(1)  # Wait one second.
            count += self.delta  # Increment `count` by the configured `delta`.
```

```yaml
# ./examples/counter/ceres.yaml
# All essential configuration for your project is stored in `ceres.yaml`.

# Ceres persists component state, logs, messages and alerts in this database. If this section is
# omitted, a temporary database will be used.
database:
  type: sqlite
  path: ./local/database.sqlite # This will be created automatically.

# Projects can declare any number of components, nested or otherwise.
components:
  - name: counter-a
    class: example.counter.Counter # Specify the component class by providing an import path.
    arguments: # These values are passed to the component's constructor.
      initial: 5 # Start counting from 5.
  - name: counter-b
    class: example.counter.Counter
    arguments:
      initial: 100 # Start counting from 100.
      delta: -5 # Decrement by 5 every second.

# The component definitions above are roughly equivalent to:
# Counter(name="counter-a", initial=5)
# Counter(name="counter-b", initial=100, delta=-5)
```

```sh
ceres run counter-a # Log numbers from 5 to infinity, incrementing by 1, until cancelled.
ceres run counter-b # Log numbers from 100 to negative infinity, decrementing by 5, until cancelled.
ceres run all       # Run both components concurrently in the foreground.

ceres service start # Start the Ceres engine as a background service that persists after logout and/or reboot.
ceres status        # Check to see if the service is running.
ceres start all     # Start all components.
ceres enable all    # Enable all components, making them automatically restart when the service is started.
ceres status        # Check to see all components are running and enabled.

ceres service stop  # Stop the background service.
```

## Documentation

To learn more about Ceres, take a look at our documentation.

| Page                                         | Description                                   |
| -------------------------------------------- | --------------------------------------------- |
| [Installing](./docs/installing.md)           | How to install Ceres on your machine.         |
| [Getting Started](./docs/getting-started.md) | How to set up and run a basic project.        |
| [Components](./docs/components.md)           | How components work.                          |
| [Development](./docs/development.md)         | How to help improve the Ceres project itself. |
