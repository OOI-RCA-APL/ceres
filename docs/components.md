# Components

Components are configurable Python objects which perform asyncronous work, and can be organized into a tree hierarchy managed by the Ceres engine.

## Features

### Configuration

Components are Python dataclasses, so their configuration is defined by their class attributes.

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
    async def do__print_random(self) -> None:
        while True:
            self.log.info(randint(self.low, self.high))  # Print a random integer within the configured range.
            await sleep(self.interval.total_seconds())  # Wait the configured interval.


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

And run it using the `ceres run` command.

```sh
$ ceres run random
...
[2023-11-14 11:00:12.287] [INFO] [@random] 70
[2023-11-14 11:00:12.789] [INFO] [@random] 94
[2023-11-14 11:00:13.293] [INFO] [@random] 50
[2023-11-14 11:00:13.797] [INFO] [@random] 86
[2023-11-14 11:00:14.301] [INFO] [@random] 82
```

Component classes can be reused, so if we need two instances of our `Random` class, we just define another.

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
[2023-11-14 11:15:51.879] [INFO] [@random] [event] [routine-started] {"routine":"do__print_random"}
[2023-11-14 11:15:51.881] [INFO] [@random] 94
[2023-11-14 11:15:51.888] [INFO] [@random-b] [event] [started] {}
[2023-11-14 11:15:51.891] [INFO] [@random-b] [event] [routine-started] {"routine":"do__print_random"}
[2023-11-14 11:15:51.894] [INFO] [@random-b] -8
[2023-11-14 11:15:52.384] [INFO] [@random] 56
[2023-11-14 11:15:52.886] [INFO] [@random] 65
[2023-11-14 11:15:52.897] [INFO] [@random-b] 8
```
