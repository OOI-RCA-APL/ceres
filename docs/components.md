| Previous                        |
| ------------------------------- |
| [Getting Started](../README.md) |

# Components

Components are Python objects which perform asyncronous work. They are easily configurable, and can be organized into logical hierarchies.

## Configuration

A component's configuration is defined by the typed attributes in its class.

_All components are dataclasses, so attributes are per-instance, and can be passed via the component's constructor, or more commonly, through the component's `arguments` configuration in `ceres.yaml`._

```python
# ../examples/random/example/random.py

import asyncio
from asyncio import sleep
from datetime import timedelta
from random import randint

from ceres import Component, routine
from ceres.data import TimeDelta


class Random(Component):
    low: int
    high: int
    interval: TimeDelta = timedelta(seconds=1)

    @routine
    async def routine__print_random(self) -> None:
        while True:
            self.log.info(randint(self.low, self.high))  # Print a random integer within the configured range.
            await sleep(self.interval.total_seconds())  # Wait the configured interval.


# This section is only included for example.
if __name__ == "__main__":

    async def main() -> None:
        component = Random(low=1, high=100)
        await component.run()

    asyncio.run(main())  # Logs a random number between 1 and 100 every second until cancelled.
```

```
$ python ./random.py
[2023-11-14 10:17:02.963] [INFO] [@] 19
[2023-11-14 10:17:03.968] [INFO] [@] 54
[2023-11-14 10:17:04.972] [INFO] [@] 99
...
```

If we want to run this component using the Ceres engine, we can define its configuration in `ceres.yaml`.

```yaml
# ../examples/random/ceres.yaml

components:
  - name: random
    class: example.random.Random
    arguments:
      low: 50
      high: 100
      interval: 0.5s
```

```sh
$ ceres run random
...
[2023-11-14 11:00:12.287] [INFO] [@random] 70
[2023-11-14 11:00:12.789] [INFO] [@random] 94
[2023-11-14 11:00:13.293] [INFO] [@random] 50
[2023-11-14 11:00:13.797] [INFO] [@random] 86
[2023-11-14 11:00:14.301] [INFO] [@random] 82
```

Component classes can be reused, so if we need two instances of our `Random` class, just add another component to `ceres.yaml`.

```yaml
# ../examples/random/ceres.yaml

components:
  - name: random
    class: example.random.Random
    arguments:
      low: 50
      high: 100
      interval: 0.5s
  - name: random-b
    class: example.random.Random
    arguments:
      low: -10
      high: 10
      interval: 1s
```

```sh
$ ceres run all
[2023-11-14 11:15:51.877] [INFO] [@random] [event] [started] {}
[2023-11-14 11:15:51.879] [INFO] [@random] [event] [routine-started] {"routine":"routine__print_random"}
[2023-11-14 11:15:51.881] [INFO] [@random] 94
[2023-11-14 11:15:51.888] [INFO] [@random-b] [event] [started] {}
[2023-11-14 11:15:51.891] [INFO] [@random-b] [event] [routine-started] {"routine":"routine__print_random"}
[2023-11-14 11:15:51.894] [INFO] [@random-b] -8
[2023-11-14 11:15:52.384] [INFO] [@random] 56
[2023-11-14 11:15:52.886] [INFO] [@random] 65
```

## Addressing

Components can be grouped together into a _tree hierarchies_ much like directories in a file system. All components in the `components` list of `ceres.yaml` are _children_ of the root component at address `@`.

_All components have an "address." Addresses are the character `@`, followed the names of the subcomponents from highest to lowest, separated by `.`. For example, the address `@a.b` refers to the the component named `b`, which is a child of the component `a`, which in turn is a child of `@`._

A component and all its subcomponents is called a _unit_. To group our `Random` components into a unit called `random`, define a `random` component and add them as child components.

```yaml
components:
  - name: random
    # The "class" is omitted here, and defaults to `Component`.
    components:
      - name: a
        class: example.random.Random
        arguments:
          low: 50
          high: 100
          interval: 0.5s
      - name: b
        class: example.random.Random
        arguments:
          low: 50
          high: 100
          interval: 0.5s
```

These components have the addresses `@random.a` and `@random.b` respectively.

```sh
ceres run random.a # Run `@random.a` and its parent component `@random`.
ceres run random.b # Run `@random.b` and its parent component `@random`.
ceres run random:all # Run all components in the `@random` unit.
ceres run all # Run all components in the project, which in this case is the same as `@random:all`.
```

## Routines

Components can declare one or more _routines_. Routines are methods which execute concurrently when the component is started, and are cancelled when stopped.

```python
# ../examples/csv-generator/example/generator.py

import csv
from asyncio import sleep
from pathlib import Path
from random import choice

from ceres import Component, routine


class CSVNameGenerator(Component):
    output: Path

    @routine
    async def routine__startup(self) -> None:
        """
        This routine will run once on startup.
        """
        self.log.info("Starting up...")

    @routine(restart="always", restart_delay=5)
    async def routine__write(self) -> None:
        """
        This routine will run on startup and execute forever, restarting if it crashes for any
        reason.
        """
        while True:
            self.output.parent.mkdir(parents=True, exist_ok=True)

            exists = self.output.exists()
            with self.output.open("a+") as stream:
                writer = csv.writer(stream)
                if not exists:
                    writer.writerow(["first", "last"])

                first, last = (
                    self.__get_random_first_name(),
                    self.__get_random_last_name(),
                )

                row = [first, last]
                writer.writerow(row)
                self.log.info(row)

            await sleep(1)

    @routine
    async def routine__log_file_size(self) -> None:
        """
        This routine will also run on startup and execute forever, but will not restart on exit or
        error.
        """
        while True:
            if self.output.exists():
                size = self.output.stat().st_size
                self.log.info(f"'{self.output}' is now {size} bytes.")
            else:
                self.log.info(f"'{self.output}' has not been created yet.")

            await sleep(5)

    def __get_random_first_name(self) -> str:
        return choice(["Alice", "Bob", "Charlie", "Diane"])

    def __get_random_last_name(self) -> str:
        return choice(["Montgomery", "Gonzalez", "Dunsworth", "Paris"])
```

```yaml
# ../examples/csv-generator/ceres.yaml

components:
  - name: generator
    class: example.generator.RandomCSVNameGenerator
    arguments:
      output: ./output.csv
```

```sh
$ ceres run all
...
[2023-11-14 13:49:07.886] [INFO] [@generator] 'output.csv' is now 186 bytes.
[2023-11-14 13:49:07.908] [INFO] [@generator] ['Bob', 'Paris']
[2023-11-14 13:49:08.911] [INFO] [@generator] ['Diane', 'Montgomery']
[2023-11-14 13:49:09.915] [INFO] [@generator] ['Charlie', 'Montgomery']
[2023-11-14 13:49:10.918] [INFO] [@generator] ['Diane', 'Paris']
[2023-11-14 13:49:11.921] [INFO] [@generator] ['Alice', 'Paris']
[2023-11-14 13:49:12.890] [INFO] [@generator] 'output.csv' is now 253 bytes.
[2023-11-14 13:49:12.924] [INFO] [@generator] ['Charlie', 'Dunsworth']
[2023-11-14 13:49:13.928] [INFO] [@generator] ['Diane', 'Gonzalez']
[2023-11-14 13:49:14.933] [INFO] [@generator] ['Alice', 'Paris']
[2023-11-14 13:49:15.937] [INFO] [@generator] ['Diane', 'Dunsworth']
[2023-11-14 13:49:16.942] [INFO] [@generator] ['Diane', 'Montgomery']
...
```

You can view the generated names in `output.csv`.
