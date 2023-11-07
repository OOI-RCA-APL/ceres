# Components

Components are configurable Python objects which perform asyncronous work. They're similar to threads, but many added features.

## Async

Components run in `asyncio` coroutines. This makes them easier to reason about and lighter weight than threads or processes.

```python
import asyncio

from ceres import Component, routine

class Counter(Component):
    # This is run the component is started, and cancelled when stopped.
    @routine
    async def count(self):
        count = 1
        while True:
            self.log.info(count)
            await asyncio.sleep(1)
            count += 1


async def main():
    component = Counter()
    component.start()
    await asyncio.sleep(5)
    component.stop()


asyncio.run(main()) # Prints numbers 1-5, then exits.
```

## Declarative

Components can be declared in config file called `ceres.yaml`.

Arguments needed by a component can be declared on the class, and will subsequently be parsed from their `arguments`.

```python
 # <example>/counter.py
 import asyncio

 from ceres import Component, routine

 class Counter(Component):
     initial: int = 1

     @routine
     async def count(self):
         count = self.initial
         while True:
             self.log.info(count)
             await asyncio.sleep(1)
             count += 1
```

```yaml
# <example>/ceres.yaml
components:
  - name: counter
    class: counter.Counter
    arguments:
      initial: 5
```

```sh
ceres run all  # Prints numbers starting from 5 until cancelled.
```

1. Components can be managed in a single background service and managed either from the Ceres CLI or Web Console.

   ```yaml
   # <example>/ceres.yaml
   service:
     name: counter-service # Name of background service.
   server:
     port: 8080 # Host the web console on port 8080.
   components:
     - name: counter-a
       class: counter.Counter
       arguments:
         initial: 1
     - name: counter-b
       class: counter.Counter
       arguments:
         initial: 100
   ```

   ```
   ceres service start     # Start Ceres as an background service, persisting after logout and/or reboot.
   ceres start all         # Start all components.
   ceres enable all        # Enable all components, making them automatically run on reboot.
   ceres stop counter-b    # Stop "counter-b" specifically.
   ceres start counter-b   # Start "counter-b" again.
   ceres disable counter-a # Disable "counter-a" to prevent it from running on restart.
   ceres service stop      # Stop and delete the background service.
   ```

2. Components can easily run multiple tasks in parallel as "routines."

```python
  # <example>/counter.py
  import asyncio

  from ceres import Component, routine

  class Counter(Component):
      initial: int = 1

      # This will be run concurrently with `count_down`.
      @routine
      async def count_up(self):
          count = self.initial
          while True:
              self.log.info(count)
              await asyncio.sleep(1)
              count += 1

      @routine
      async def count_down(self):
          count = self.initial
          while True:
              self.log.info(count)
              await asyncio.sleep(1)
              count -= 1
```

```sh
ceres run all  # Count up and down concurrently from `initial` until cancelled.
```
