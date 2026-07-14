import asyncio
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any, TypedDict, Unpack, cast, overload, override

from pydantic import ByteSize, Field

from ceres.__internal__.manager import BaseComponentTaskManager
from ceres.channel import Channel
from ceres.component import BoundField, BoundFieldArgs
from ceres.concurrency import sleep
from ceres.connection.buffer import Buffer as Buffer
from ceres.connection.buffer import Chunk as Chunk
from ceres.connection.source import ConnectFailed as ConnectFailed
from ceres.connection.source import ConnectTimeout as ConnectTimeout
from ceres.connection.source import Source as Source
from ceres.connection.source import TCPSource as TCPSource
from ceres.connection.source import UNIXSocketSource as UNIXSocketSource
from ceres.connection.splitter import SplitByChunk as SplitByChunk
from ceres.connection.splitter import SplitByDelay as SplitByDelay
from ceres.connection.splitter import SplitByLine as SplitByLine
from ceres.connection.splitter import SplitByRegex as SplitByRegex
from ceres.connection.splitter import Splitter as Splitter
from ceres.connection.splitter import Unsplit as Unsplit
from ceres.connectivity import Connectivity
from ceres.constants import DEFAULT_BUFFER_DROP, DEFAULT_BUFFER_READ_SIZE, DEFAULT_BUFFER_SIZE
from ceres.data import DataObject, Name, PositiveTimeDelta, ToBytes, validate
from ceres.event import (
    BufferOverflowEvent,
    ConnectedEvent,
    ConnectFailedEvent,
    ConnectingEvent,
    ConnectionAddedEvent,
    ConnectionLostEvent,
    ConnectionRemovedEvent,
    ConnectionStartedEvent,
    ConnectionStoppedEvent,
    ConnectTimeoutEvent,
    DisconnectedEvent,
    DisconnectingEvent,
    MessageReceivedEvent,
    MessageSentEvent,
    ReceiveTimeoutEvent,
    ReconnectScheduledEvent,
)
from ceres.loaded import Loaded
from ceres.message import (
    BoundMessageManager,
    Message,
    MessageData,
    MessageDirection,
    MessageFilter,
    MessageFilterArgs,
)
from ceres.schedule import IntervalSchedule, Schedule
from ceres.tasklet import Tasklet
from ceres.timing import delta, utc

if TYPE_CHECKING:
    from ceres.component import ComponentSystem
else:
    ComponentSystem = object

__all__ = (
    "Connection",
    "ConnectionField",
    "ConnectionDefaults",
    # .source
    "ConnectionInactive",
    "ConnectionLost",
    "Source",
    "ConnectFailed",
    "ConnectTimeout",
    "TCPSource",
    "UNIXSocketSource",
    # .splitter
    "Splitter",
    "SplitByChunk",
    "SplitByDelay",
    "SplitByLine",
    "SplitByRegex",
    "Unsplit",
)


class ConnectionException(Exception):
    """Base exception for connection-level errors."""


class ConnectionInactive(ConnectionException):
    """Raised when an operation requires an active connection but the connection is not connected."""


class ConnectionLost(ConnectionException):
    """Raised when an established connection is lost during a send or receive operation."""


class ConnectionDefaults(TypedDict, total=False):
    """Default values that can be applied to a `Connection` when constructed via a field."""

    name: Name
    source: Loaded[Source]
    splitter: Loaded[Splitter] | None
    suffix: bytes | None

    buffer_read_size: int | str
    buffer_size: int | str
    buffer_drop: int | str

    connect_timeout: PositiveTimeDelta | float | str | None
    receive_timeout: PositiveTimeDelta | float | str | None
    reconnect_schedule: Schedule | str | None


class ConnectionFieldArgs(BoundFieldArgs, ConnectionDefaults, total=False):
    """`TypedDict` of keyword arguments accepted by `ConnectionField`."""

    defaults: ConnectionDefaults | None


class ConnectionField(BoundField["Connection"]):
    """Pydantic field descriptor that declares a `Connection` slot on a component.

    Connection-specific keyword arguments (e.g. `source`, `splitter`, `buffer_size`) are
    extracted from `kwargs` and folded into the `defaults` mapping so the connection is
    preconfigured when the component is instantiated.
    """

    __slots__ = ()

    @dataclass(slots=True)
    class Marker(BoundField.Marker):
        """Annotation marker identifying a field as a `ConnectionField`."""

    def __init__(
        self,
        default: Any = ...,
        **kwargs: Unpack[ConnectionFieldArgs],
    ):
        """Create a `ConnectionField` with optional connection defaults.

        Args:
            default: Default value for the field, or `...` to require explicit assignment.
            **kwargs: Connection-level keyword arguments and standard `BoundFieldArgs`.
                Any key that matches a `Connection` model field is moved into the `defaults`
                mapping automatically.
        """
        defaults: ConnectionDefaults | None = kwargs.get("defaults")
        if defaults is not None:
            kwargs["defaults"] = defaults = {**defaults}

        # Move any connection-model keyword arguments into `defaults` so they are applied
        # when the connection is constructed from configuration.
        for field in Connection.__pydantic_fields__:
            if field in kwargs:
                assigned: Any = kwargs.pop(field)  # type: ignore
                if defaults is None:
                    defaults = {}

                defaults[field] = assigned

        if defaults:
            kwargs["defaults"] = defaults

        super().__init__(default, **cast("ConnectionFieldArgs", kwargs))


class Connection(DataObject, Tasklet, slots=True):
    """A managed byte-oriented connection driven by a `Source` transport.

    `Connection` handles the full lifecycle of a single connection, including establishing
    the transport, buffering and splitting incoming bytes into messages, sending outbound
    data, and automatically reconnecting on failure. It runs as a background `Tasklet`
    managed by the owning component's `ComponentConnectionManager`.
    """

    name: Name | None = None
    """Optional name used to identify this connection within its component."""
    source: Loaded[Source]
    """Transport endpoint that provides the underlying byte stream."""
    splitter: Loaded[Splitter] | None = None
    """Strategy for splitting the receive buffer into discrete messages."""
    suffix: MessageData | None = None
    """Bytes appended to outbound data when `suffixed=True` in `send()`."""

    buffer_read_size: ByteSize = Field(default=DEFAULT_BUFFER_READ_SIZE, gt=0)
    """Maximum number of bytes to read from the source in a single call."""
    buffer_size: ByteSize = Field(default=DEFAULT_BUFFER_SIZE, gt=0)
    """Maximum buffer size before overflow handling kicks in."""
    buffer_drop: ByteSize = Field(default=DEFAULT_BUFFER_DROP, gt=0)
    """Number of bytes to drop from the front of the buffer on overflow."""

    connect_timeout: PositiveTimeDelta | None = None
    """Maximum time to wait for the source to connect before giving up."""
    receive_timeout: PositiveTimeDelta | None = None
    """Maximum time to wait for incoming data before emitting a timeout event."""
    reconnect_schedule: Schedule | None = field(
        default_factory=lambda: IntervalSchedule(
            interval=timedelta(seconds=1),
            multiplier=2,
            max=timedelta(seconds=60),
        )
    )
    """Schedule governing delay between reconnection attempts after a failure."""

    _connectivity: Connectivity = field(init=False)
    _buffer: Buffer = field(init=False)
    _system: ComponentSystem | None = field(init=False)
    _channel: Channel[Message] = field(init=False)

    Field = ConnectionField
    Defaults = ConnectionDefaults

    def __post_init__(self) -> None:
        self._connectivity = Connectivity.DISCONNECTED
        self._buffer = Buffer()
        self._system = None
        self._channel = Channel()

    @property
    def label(self) -> str:
        """Return the human-readable label of the underlying `Source`."""
        return self.source.label

    @property
    def __system__(self) -> ComponentSystem:
        """Return the owning `ComponentSystem`, creating a default one if unset."""
        from ceres.component import Component

        if self._system is None:
            self._system = Component().system

        return self._system

    @__system__.setter
    def __system__(self, system: ComponentSystem | None) -> None:
        self._system = system

    @property
    def buffer(self) -> bytes:
        """Return a snapshot of the current receive buffer contents as `bytes`."""
        return bytes(self._buffer)

    @property
    def connectivity(self) -> Connectivity:
        """Return the current `Connectivity` state of this connection."""
        return self._connectivity

    @property
    def connected(self) -> bool:
        """Return `True` if the connection is currently in the `CONNECTED` state."""
        return self._connectivity == Connectivity.CONNECTED

    @property
    def messages(self) -> BoundMessageManager:
        """Return a `BoundMessageManager` scoped to messages on this connection."""

        def filtering():
            if self.name is None:
                return MessageFilter(address=self.__system__.address)

            return MessageFilter(address=self.__system__.address, connection=self.name)

        return BoundMessageManager(self.__system__, filtering)

    async def connect(self) -> bool:
        """Attempt to establish the connection via the configured `Source`.

        Emit `ConnectingEvent` before the attempt, then `ConnectedEvent` or
        `ConnectFailedEvent` depending on the outcome. If `connect_timeout` is set and
        exceeded, emit `ConnectTimeoutEvent` and treat the attempt as failed.

        Returns:
            `True` if the connection is established when this call returns.
        """
        if self._connectivity == Connectivity.CONNECTED:
            return True

        self.__system__.events.emit(ConnectingEvent, connection=self.name)

        self._connectivity = Connectivity.CONNECTING

        error: str | None = None

        try:
            connect_timeout = self.connect_timeout
            try:
                async with asyncio.timeout(
                    connect_timeout.total_seconds() if connect_timeout is not None else None
                ):
                    connected = await self.source.connect()
            except TimeoutError:
                if connect_timeout is not None:
                    self.__system__.events.emit(
                        ConnectTimeoutEvent,
                        connection=self.name,
                        timeout=connect_timeout,
                    )
                connected = False
        except Exception as exception:
            connected = False
            if text := str(exception).strip():
                error = text

        if connected:
            self._connectivity = Connectivity.CONNECTED
            self.__system__.events.emit(ConnectedEvent, connection=self.name)
        else:
            self._connectivity = Connectivity.DISCONNECTED
            self.__system__.events.emit(ConnectFailedEvent, connection=self.name, message=error)

        return self.connected

    async def send(self, data: ToBytes, suffixed: bool = True) -> Message:
        """Send raw bytes through the connection, returning the sent `Message`.

        There is no guarantee the returned message is actually received on the remote end,
        only that the data was transmitted to the transport.

        Args:
            data: Payload to send, converted to `bytes` before transmission.
            suffixed: When `True`, append `self.suffix` to the data if it is set and the
                data does not already end with the suffix.

        Returns:
            The `Message` record created for the sent data.

        Raises:
            ConnectionInactive: If the connection is not currently connected.
            ConnectionLost: If the underlying transport fails during the send.
        """
        if not self.connected:
            raise ConnectionInactive()

        data = bytes(data)
        if suffixed:
            if self.suffix and not data.endswith(self.suffix):
                data += self.suffix

        try:
            sent = await self.source.send(data)
        except Exception:
            sent = None

        if sent is None and self.connected:
            self.__system__.events.emit(ConnectionLostEvent, connection=self.name)
            await self.disconnect()
            raise ConnectionLost()

        message = Message(
            address=self.__system__.address,
            connection=self.name,
            direction=Message.Direction.SEND,
            data=data,
        )

        self.__system__.store(message)
        self._channel.put(message)
        self.__system__.events.emit(MessageSentEvent, message=message)

        return message

    @overload
    async def receive[T](
        self,
        *,
        where: Callable[[Message], bool] | None = None,
        timeout: float | timedelta | None = None,
        default: T | Callable[[], T],
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | T: ...

    @overload
    async def receive(
        self,
        *,
        where: Callable[[Message], bool] | None = None,
        timeout: float | timedelta | None = None,
        default: ... = ...,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message: ...

    async def receive[T](
        self,
        *,
        where: Callable[[Message], bool] | None = None,
        timeout: float | timedelta | None = None,
        default: T | Callable[[], T] = ...,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | T:
        """Wait for and return the next matching message on this connection.

        Messages are matched against the optional `where` predicate and any `MessageFilter`
        keyword arguments. If `timeout` expires before a match is found, return `default`
        (calling it first if it is callable) or raise `TimeoutError` when no default was
        provided.

        Args:
            where: Optional predicate that must return `True` for a message to match.
            timeout: Maximum time to wait, as seconds or a `timedelta`.
            default: Value (or zero-argument callable returning a value) to return on
                timeout. When omitted, `TimeoutError` is raised instead.
            **kwargs: Additional `MessageFilterArgs` forwarded to `MessageFilter`.

        Returns:
            The first matching `Message`, or `default` if the timeout elapses.

        Raises:
            TimeoutError: If the timeout elapses and no `default` was supplied.
        """
        received = self._channel.read()

        timeout = delta(timeout).total_seconds() if timeout is not None else None
        if kwargs:
            query = validate(Message.Filter, kwargs)
        else:
            query = None

        try:
            async with asyncio.timeout(timeout):
                async for message in received:
                    if where is not None:
                        if not where(message):
                            continue
                    if query is not None:
                        if not query.matches(message):
                            continue

                    return message
        except TimeoutError:
            pass

        if default is ...:
            raise TimeoutError()
        if callable(default):
            return cast("Callable[[], T]", default)()

        return default

    async def disconnect(self) -> None:
        """Gracefully close the connection and clear the receive buffer.

        Emit `DisconnectingEvent` before teardown and `DisconnectedEvent` after.
        No-op if the connection is already disconnected.
        """
        if self._connectivity == Connectivity.DISCONNECTED:
            return

        self.__system__.events.emit(DisconnectingEvent, connection=self.name)

        try:
            await self.source.disconnect()
        finally:
            self._buffer.clear()
            self._connectivity = Connectivity.DISCONNECTED
            self.__system__.events.emit(DisconnectedEvent, connection=self.name)

    @override
    async def __run__(self) -> None:
        """Run the connection lifecycle loop.

        Repeatedly attempt to connect using the configured reconnect schedule, then read
        incoming data, split it into messages, and emit events until the connection is lost
        or the task is cancelled.
        """
        self.__system__.events.emit(ConnectionStartedEvent, connection=self.name)

        initialized = False

        try:
            while True:
                reconnect_trigger = (
                    self.reconnect_schedule.create_trigger()
                    if self.reconnect_schedule is not None
                    else None
                )

                while True:
                    if initialized:
                        if reconnect_trigger is None:
                            break

                        next = reconnect_trigger.get_next_fire_time()
                        if next is None:
                            break

                        delay = next - utc()

                        self.__system__.events.emit(
                            ReconnectScheduledEvent,
                            connection=self.name,
                            delay=delay,
                        )

                        await sleep(delay)

                    # Yield to event loop.
                    await sleep(0)

                    connected = await self.connect()
                    initialized = True
                    if connected:
                        break

                while self.connected:
                    received: bytes | None = None

                    try:
                        timeout = self.receive_timeout
                        try:
                            async with asyncio.timeout(
                                timeout.total_seconds() if timeout is not None else None
                            ):
                                received = await self.source.receive(self.buffer_read_size)
                        except TimeoutError:
                            if timeout is not None:
                                self.__system__.events.emit(
                                    ReceiveTimeoutEvent,
                                    connection=self.name,
                                    timeout=timeout,
                                )
                            received = None
                    except Exception:
                        self.__system__.log.error(traceback.format_exc())

                        received = None

                    # Yield to event loop.
                    await sleep(0)

                    # If `receive` returns `None`, an empty `bytes`, or throws an exception, the
                    # connection is considered lost.
                    if not received:
                        if self.connected:
                            self.__system__.events.emit(ConnectionLostEvent)

                            await self.disconnect()

                        break

                    # Keep local reference to the buffer for performance.
                    buffer = self._buffer
                    # Append received data to the buffer.
                    buffer.push(received, utc())

                    # Drop data from the buffer if it exceeds the buffer size limit.
                    dropped = buffer.pop_to(self.buffer_size, self.buffer_drop)
                    if dropped is not None:
                        self.__system__.events.emit(
                            BufferOverflowEvent,
                            size=ByteSize(buffer.size),
                            limit=ByteSize(self.buffer_size),
                            dropped=ByteSize(len(dropped.data)),
                        )

                    address = self.__system__.address
                    for chunk in buffer.drain(self.splitter, linearize=True):
                        message = Message(
                            address=address,
                            connection=self.name,
                            timestamp=chunk.timestamp,
                            direction=MessageDirection.RECEIVE,
                            data=chunk.data,
                        )

                        self.__system__.store(message)
                        self._channel.put(message)
                        self.__system__.events.emit(MessageReceivedEvent, message=message)
        finally:
            await self.disconnect()
            self.__system__.events.emit(ConnectionStoppedEvent, connection=self.name)

    @override
    async def __stop__(self) -> None:
        """Disconnect the connection when the tasklet is stopped."""
        await self.disconnect()


class ComponentConnectionManager(BaseComponentTaskManager[Connection]):
    """Manage the set of `Connection` instances owned by a single component.

    Handle adding and removing connections, binding each connection to the component's
    system, and running each connection as a background task.
    """

    __slots__ = ()

    @override
    def add(self, connection: Connection) -> None:
        """Bind `connection` to this component's system, register it, and emit an event.

        Args:
            connection: The connection to add.
        """
        connection.__system__ = self.__system__
        super().add(connection)
        if connection.name is not None:
            self.__system__.events.emit(ConnectionAddedEvent, connection=connection.name)

    @override
    async def remove(self, name: Name) -> Connection | None:
        """Stop and remove the connection with the given `name`, emitting an event.

        Args:
            name: Name of the connection to remove.

        Returns:
            The removed `Connection`, or `None` if no connection with that name existed.
        """
        connection = await super().remove(name)
        if connection is not None:
            self.__system__.events.emit(ConnectionRemovedEvent, connection=name)
            connection.__system__ = None

        return connection

    @override
    async def process(self, connection: Connection) -> None:
        """Run a connection's lifecycle loop as a managed background task.

        Args:
            connection: The connection to run.
        """
        await connection.run()
