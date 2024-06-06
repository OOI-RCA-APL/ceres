# Example

## The Problem

Let's say we have a sensor that sends a message over a TCP connection every second. Each message is formatted as plain text containing a temperature and humidity reading, separated by a space and terminated by a new-line character.

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

For simplicity, let's say this temperature sensor is running on the our local machine and sending data back on port `4000`. Our goal is to write these temperature and humidity readings to file in CSV format, separated by day.

## Simulator

Because this isn't a real sensor, we'll have to simulate it. Create a Python script containing the following code, and run it with `python simulator.py`.

_[simulator.py](../examples/intro/intro/simulator.py)_

```python
import random
import socket
from time import sleep

host = "localhost"
port = 4000

if __name__ == "__main__":
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(1)

    print(f"Listening on {host}:{port}...")

    try:
        while True:
            client, (client_host, client_port) = server.accept()
            print(f"Accepted: {client_host}:{client_port}")

            try:
                while True:
                    temperature = round(random.uniform(15, 30), 2)
                    humidity = round(random.uniform(30, 70), 2)
                    data = f"T:{temperature} H:{humidity}\n"

                    client.send(data.encode())
                    print(f"Sent: {data}")
                    sleep(1)
            except ConnectionError:
                print(f"Disconnected: {client_host}:{client_port}")
            finally:
                client.close()
    except KeyboardInterrupt:
        print("Interrupted. Exiting...")
        pass
    finally:
        server.close()
```

You should see this output, which means the script is running:

```txt
Listening: localhost:4000
```

## Project Setup

Now, while the above script is listening on port `4000`, let's set up a Ceres project.

Create a project directory with a configuration file named `ceres.yaml`.

```sh
mkdir example
cd example
touch ceres.yaml
```

_The file names `ceres.yml` and `ceres.json` are also supported._

### Configuration

Next, we need to configure our project. Edit `ceres.yaml` and add the following sections.

#### Server

```yaml
server:
  port: 8080
```

This will tell Ceres to provide the web console and API on port `8080`.

#### Database

```yaml
database:
  type: sqlite
  path: ./database.sqlite
```

This tells the Ceres engine where it should store internal data, including component state, messages, alerts and logs. For this project, we're just using a simple SQLite database at the root of the project.

_The database will be created and initialized automatically. There's no need to create it yourself. PostgreSQL is also supported, but for small projects SQLite is enough._

#### Components

```yaml
components:
  - name: connection
    class: ceres.TCPConnection
    arguments:
      host: localhost
      port: 4000
      separator: "\n"
```

For now, we declare a component named `connection` as an instance of the standard, built-in component class `TCPConnection`, and provide it with some configuration via `arguments`.

This component, globally addressed as `@connection`, will automatically bind to `localhost:4000`, and split the incoming bytes into messages by new-line. Each message will be assigned a timestamp, associated with the `@connection` address, and finally, stored in the internal database.

_If the component cannot connect to the host/port combination, or the connection is lost for some reason, it will attempt to reconnect automatically using an exponential backoff._

#### Final

Our full `ceres.yaml` configuration file should look like this.

[ceres.yaml](../examples/intro/ceres.yaml)

```yaml
server:
  port: 8080
database:
  type: sqlite
  path: ./local/database.sqlite
components:
  - name: connection
    class: ceres.TCPConnection
    arguments:
      host: localhost
      port: 4000
      separator: "\n"
```

## Running

With our configuration file ready, we can can run project using the `ceres run all` command.

```sh
ceres run all
```

The `run` command reads the `ceres.yaml` configuration file in the working directory, and starts a Ceres `Engine` to run it.

_The `all` argument is used to make the engine run every components in the project on startup. This is useful for development. In production or with a more complex project, you'll likely want to use the `start`, `stop`, `enable` and `disable` commands to manage components individually._

#### Engine Output

You should see the similar output to the following, which means the engine is running and the `@connection` component has connected to the simulator and is receiving messages:

```log
[2023-09-04 15:14:23.491] [INFO] [~] Checking database configuration...
[2023-09-04 15:14:23.500] [INFO] [~] Connected to database successfully.
[2023-09-04 15:14:23.502] [INFO] [~] Database configuration is valid.
[2023-09-04 15:14:23.503] [INFO] [~] Checking component configurations...
[2023-09-04 15:14:23.504] [INFO] [~] Component '@': OK
[2023-09-04 15:14:23.505] [INFO] [~] Component '@connection': OK
[2023-09-04 15:14:23.506] [INFO] [~] Component configurations appear valid.
[2023-09-04 15:14:23.526] [INFO] [~] Loaded '@' as <class 'ceres.component.Component'>.
[2023-09-04 15:14:23.531] [INFO] [~] Loaded '@connection' as <class 'ceres.standard.connections.tcp.TCPConnection'>.
[2023-09-04 15:14:23.537] [INFO] [~] [event] [started] {}
[2023-09-04 15:14:23.541] [INFO] [~] Listening on socket at
'/tmp/ceres-d03d1c6a02a932acd99ac929c5e250fabab66807.sock'.
[2023-09-04 15:14:23.542] [INFO] [~] Listening on port 8080...
[2023-09-04 15:14:23.576] [INFO] [@] [event] [started] {}
[2023-09-04 15:14:23.624] [INFO] [@connection] [event] [started] {}
[2023-09-04 15:14:23.626] [INFO] [@connection] [event] [routine-started] {"routine":"routine__process_connection"}
[2023-09-04 15:14:23.627] [INFO] [@connection] [event] [connecting] {}
[2023-09-04 15:14:23.629] [INFO] [@connection] [event] [routine-started] {"routine":"routine__process_disconnect"}
[2023-09-04 15:14:23.631] [INFO] [@connection] [event] [connected] {}
[2023-09-04 15:14:23.633] [INFO] [@connection] [event] [message-received]
{"message":{"id":"936d4a5c-920e-4b7b-815e-fe3f516ee5d2","address":"@connection","timestamp":"2023-09-04T22:14:23.6332
98Z","direction":"receive","content":"T:25.19 H:37.3\n"}}
[2023-09-04 15:14:24.632] [INFO] [@connection] [event] [message-received]
{"message":{"id":"7f871ed6-4df4-434d-9c7a-e19a1a71bcca","address":"@connection","timestamp":"2023-09-04T22:14:24.6318
96Z","direction":"receive","content":"T:27.26 H:33.86\n"}}
[2023-09-04 15:14:25.632] [INFO] [@connection] [event] [message-received]
{"message":{"id":"a4fcbeb8-ba2b-4133-8c5e-1818b0c2d332","address":"@connection","timestamp":"2023-09-04T22:14:25.6326
99Z","direction":"receive","content":"T:21.36 H:50.11\n"}}
...
```

#### Simulator Output

The simulator output should look something like this:

```txt
Accepted: 127.0.0.1:50359
Sent: 'T:25.19 H:37.3\n'
Sent: 'T:27.26 H:33.86\n'
Sent: 'T:21.36 H:50.11\n'
...
```

Notice that for every message the simulator sends, the engine receives it and logs a message received event.

### Web Console

Now that the engine is running, we can open the web console at [http://localhost:8080](http://localhost:8080).

Click on the `@connection` tab in the left sidebar to view the component page, then click on the `Messages` tab to view the messages received by the component. The message views in the console (as well as alert and log views) supports infinite scrollback and search.

![Screenshot of received messages in web console.](../images/web-console-messages.png)

## CLI

Open up another terminal in the project directory, enter your virtual environment, and try running the following commands.

#### Status

The status command shows information about the state of the engine and its components.

```sh
$ ceres status

Engine
┌────────────────────────────┬─────────┬──────┬─────────────────────────────┐
│ Configuration              │ Running │ Port │ Socket                      │
├────────────────────────────┼─────────┼──────┼─────────────────────────────┤
│ /home/jploskey/cere…       │ Yes     │ 8080 │ /tmp/ceres-d03d1c6a02a932a… │
└────────────────────────────┴─────────┴──────┴─────────────────────────────┘
Components
┌─────────────┬─────────┬─────────┐
│ Address     │ Running │ Enabled │
├─────────────┼─────────┼─────────┤
│ @           │ Yes     │ No      │
│ @connection │ Yes     │ No      │
└─────────────┴─────────┴─────────┘
```

The `Engine` section shows that the engine is running, the server is available on port `8080`, and the Unix socket the CLI uses to communicate with the engine is in the `/tmp` directory of the current machine.

The `Components` section shows of the state of our components.

_You'll notice here, that that in addition to `@connection`, there is another component with the address `@`. Tis is the "root" component. Ceres components form a tree, with one implicit component at the top. This hierarchical structure allows components to be organized into logical groups._

For our project, the `@` and `@connection` components are running but disabled, meaning that unless we run the engine using the `all` selector, they will not be started automatically.

#### Start & Stop Commands

The `start` and `stop` commands allow you to start/stop components at any time.

To stop the `@connection` component, run the `stop` command.

```sh
ceres stop @connection
```

Do note that when using the CLI, the `@` prefix is optional. Therefor you can run the same command without it.

```sh
ceres stop connection
```

The `status` command will now show the `@connection` component is no longer running.

_However, the root component `@`, still is. A component can only run if its parent component is running. Therefor, stopping the root component will stop all components in the project. If you did want to stop the root component for any reason, run `ceres stop @`, or `ceres stop all`._

Now, to start our connection component again, run the `start` command.

```sh
ceres start connection # Starts the @connection component and the parent root component.
```

If you want to start or stop all components in the project, you can run:

```sh
ceres start all # Start all components.
ceres stop all # Stop all components.
```

#### Enable & Disable Commands

The `enable` and `disable` commands allow you to enable/disable components at any time.

First, let's stop the engine using `Ctrl+C`, then start it again using the `run` command.

```sh
ceres run
```

You'll notice, however, by the output of the above command that no components are running. This is because we're not passing the `all` selector, meaning components must be explitly enabled to run on startup.

If you do want a component to run on startup, use the `enable` command.

```sh
ceres enable connection
```

The `status` command will now show `@connection` as enabled.

Now, stop the engine using `Ctrl+C`, and restart it using `ceres run`:

```sh
ceres run
```

You'll notice that the `@connection` component is now running automatically.

To disable a component, you can use the `disable` command:

```sh
ceres disable connection
```

To enable or disable all components in the project, you can use the `all` selector.

```sh
ceres enable all # Enable all components.
ceres disable all # Disable all components.
```

#### Up & Down Commands

The `up` command is synonym for running `enable` and `start`. The `down` command is the opposite, meaning `disable` and `stop`.

```sh
ceres up connection # Enable and start the @connection component.
ceres down connection # Disable and stop the @connection component.
```

The `up` and `down` commands also take selectors just like the other commands.

```sh
ceres up all # Enable and start all components.
ceres down all # Disable and stop all components.
```

#### Service Commands

To manage Ceres as user-level background service, use the `service` command:

```sh
ceres service start # Start background process, creating a service file automatically.
ceres service status # Check status of background process.
ceres service stop # Stop background process, deleting the service file automatically.
```

_On Linux, the service is managed using Systemd `--user` commands, and `loginctl enable-linger` is run automatically in order to make it persist after logout._

_On macOS, the service is managed using Launchd commands._

_The `service` commands are currently only supported on Linux and macOS._

## Custom Components

So far we've only used the built-in `TCPConnection` component to receive raw messages from the simulator. Now let's get to the interesting part, and create our own components. In your project directory, create a Python module named `intro` with the following structure:

```
intro/
├── __init__.py
├── driver.py
```

_The `__init__.py` file is required to make the `intro` directory a Python module we can import from._

Add the following code to `driver.py`:

```python
import csv
from datetime import datetime
from pathlib import Path

from ceres import Component, Connection, Message, Ref, listener
from ceres.data import DataObject
from ceres.event import MessageReceivedEvent
from ceres.parsing import Parser


class Driver(Component):
    connection: Ref[Connection]
    out: Path

    @listener(reference="connection", event=MessageReceivedEvent)
    async def on__message(self, event: MessageReceivedEvent) -> None:
        data = MessageData.parse(event.message)

        self.out.parent.mkdir(parents=True, exist_ok=True)
        with self.out.open("a+") as file:
            writer = csv.writer(file)
            row = [
                data.timestamp.isoformat(),
                data.temperature,
                data.humidity,
            ]

            self.system.log.info(row)
            writer.writerow(row)


class MessageData(DataObject):
    timestamp: datetime
    temperature: float
    humidity: float

    @classmethod
    def parse(cls, message: Message) -> "MessageData":
        parser = Parser(message.content)
        parser.eat(b"T:")
        temperature = parser.eat_float()
        parser.eat_space()
        parser.eat(b"H:")
        humidity = parser.eat_float()

        return MessageData(
            timestamp=message.timestamp,
            temperature=temperature,
            humidity=humidity,
        )
```

Then, register the component in `ceres.yaml`, alongside the connection component:

```yaml
components:
  - name: connection
    class: ceres.TCPConnection
    arguments:
      host: localhost
      port: 4000
      separator: "\n"
  - name: driver
    class: intro.driver.Driver
    arguments:
      connection: "@connection"
      out: ./local/messages.csv
```

There are many things to unpack here, so lets go through them one by one:

1. The `Driver` class inherits from `Component`. This is required.
2. All subclasses of `Component` are actually [Pydantic dataclasses](https://docs.pydantic.dev/latest/concepts/dataclasses), meaning attributes defined in a component's class body are per-instance fields, assignable by arguments in the class's constructor.
3. Values assigned in a component's `arguments` configuration are passed directly to the component's constructor, and subsequently validated according to the type hints of the associated field.

   The component section of the above `ceres.yaml` file is equivalent to:

   ```python
   from ceres import TCPConnection

   from intro.driver import Driver

   connection = TCPConnection(
      host="localhost",
      port=4000,
      separator="\n"
   )

   driver = Driver(
      connection=connection,
      out=Path("./messages.csv")
   )
   ```

4. The `connection` field is defined as a `Ref[Connection]`, meaning it accepts a "reference" to a `Connection` component. Within `ceres.yaml`, addresses of components can be passed to reference fields and Ceres will assign the component automatically on load.
5. The `out` field accepts a file system path the driver will write to.
6. The `Driver` component defines an event listener called `on__message` using the `@on` decorator. `on__message` will be invoked whenever a `MessageReceivedEvent` is emitted by the component _assigned to the field_ `connection`, which in the above configuration is our `TCPConnection` `@connection`.

   _At runtime, `Driver` can use `self.connection` to access the connection component instance. For example, the driver could execute `await self.connection.send(b"abc")` to send data to the device over TCP._

7. `MessageData` is a structured representation of the data received from a single message. Here, a `MessageData` can be parsed from a `Message` using the `parse` class method, and we use that method to extract data from each message and write it to file.

   _`DataObject` is simply a subclass of Pydantic's [`BaseModel`](https://docs.pydantic.dev/latest/concepts/models/) with different default settings, though more functionality may be added over time._

8. The `parse` method of `MessageData` uses the `Parser` class to parse data from message content. You don't _need_ to use `Parser` to do this, but it's available to you if you want it.
