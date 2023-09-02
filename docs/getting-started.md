| Previous                      | Next                          |
| ----------------------------- | ----------------------------- |
| [Installing](./installing.md) | [Components](./components.md) |

# Getting Started

It's difficult to explain how Ceres works without a concrete example, so this page will be running through a simple example project, explaining Ceres' core concepts along the way.

## Problem

Let's say we have a sensor that sends a simple message over a TCP connection every second. Each message it sends is formatted as plain text containing a temperature and humidity reading, separated by a space and terminated by a new-line character.

```python
# Example message bytes.
messages = [
    b"T:20.55 H:56.1\n",
    b"T:20.55 H:56.1\n",
    b"T:20.54 H:56.3\n",
    b"T:20.50 H:56.0\n",
    b"T:20.54 H:56.1\n",
    ...
]
```

For simplicity let's say this temperature sensor is running on the our local machine and sending data back on port `4000`. Our goal is to write these temperature and humidity readings to file in CSV format, separated by day.

## Simulation

Because this isn't a real sensor, we'll have to simulate it.

```python
# simulation.py

import random
import socket
from time import sleep

host = 'localhost'
port = 4000

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((host, port))
server.listen(1)

print(f"Listening on {host}:{port}...")

try:
    while True:
        client, address = server.accept()
        print(f"Accepted: {address}.")

        try:
            while True:
                temperature = round(random.uniform(15, 30), 2)
                humidity = round(random.uniform(30, 70), 2)
                data = f"T:{temperature} H:{humidity}".encode()

                client.send(data.encode() + b'\n')
                print(f"Sent: {data}")
                sleep(1)
        finally:
            client.close()
except KeyboardInterrupt:
    pass
finally:
    server.close()
```

You can run the above in your terminal using `python simulation.py`. Just leave it running for the remainder of this tutorial.

## Project

Now, let's set up a Ceres project.

Create a directory containing a configuration file named `ceres.yaml`. The names `ceres.yml`, `ceres.json` are also supported.

```sh
mkdir example
cd example
touch ceres.yaml
```

### Configuration

Next, we need to configure our project. Edit `ceres.yaml` and add the following sections.

#### Server

```yaml
server:
  port: 8080
```

This will tell Ceres to listen on port `8080`. The server provides a web console, and an API.

#### Database

```yaml
database:
  type: sqlite
  path: ./database.sqlite
```

This section declares where Ceres should store its "core" data, including component state, messages, alerts and logs. For this project, we're using an SQLite database at the root of our project.

_The database will be created and initialized automatically, so no need to create it yourself._

_PostgreSQL is also supported, but for small to medium sized projects SQLite is enough._

#### Components

```yaml
components:
  - name: connection
    class: ceres.standard.TCPConnection
    args:
      host: localhost
      port: 4000
      separator: "\n"
```

This section declares the "components" that make up our project. Components are the core building blocks of a Ceres project. They are configurable Python objects that work together to form a robust collection system. We'll go into more detail later on.

For now, we declare a component named `connection` as an instance of the standard, built-in component type `TCPConnection` and provide it with some configuration arguments.

This component, globally addressed as `@connection`, will automatically bind to `localhost:4000`, splitting the incoming byte stream into separate messages by new-line. Each message will then be assigned a timestamp, associated with the `@connection` address, and stored in the database.

#### Configuration

Our full `ceres.yaml` configuration file should look like this.

```yaml
server:
  port: 8080
database:
  type: sqlite
  path: ./local/database.sqlite
components:
  - name: connection
    class: ceres.standard.TCPConnection
    args:
    host: localhost
    port: 4000
    separator: "\n"
```

### Running

With our configuration file ready, we can can run project using the `ceres run` command.

```sh
ceres run --all
```

The `run` command reads the `ceres.yaml` configuration file and starts a Ceres `Engine` class to run our project.

_We need to specify the `--all` flag to make the engine run all components in the project on startup. This is useful for development. In production or with a more complex project, you'll want to use the `start`, `stop`, `enable` and `disable` commands to manage components individually._

TODO
