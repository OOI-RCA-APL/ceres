import asyncio
from abc import ABC
from asyncio import Queue as AsyncQueue
from datetime import timedelta
from enum import Enum
from typing import Any, AsyncIterable

from pydantic import validator
from pydantic.dataclasses import dataclass as validated_dataclass

from .component import Component, ComponentContext, ComponentParameters
from .events import (
    ConnectedEvent,
    DisconnectedEvent,
    MessageReceivedEvent,
    MessageSentEvent,
)
from .internal.utilities import validate_positive_timedelta
from .message import Message, MessageDirection
from .path import ConnectionPath, LocalConnectionPath
from .protocols import ReferencedConnectionHandle
from .reference import Reference


@validated_dataclass(kw_only=True, frozen=True)
class ConnectionReconnect:
    interval: timedelta = timedelta(seconds=1)
    backoff: float | None = 2
    max_interval: timedelta | None = timedelta(seconds=60)

    @validator("interval", "max_interval", pre=True)
    def _validate_timedeltas(cls, value: Any) -> timedelta:
        return validate_positive_timedelta(value)


class ReconnectScheduler:
    def __init__(self, config: ConnectionReconnect) -> None:
        self.interval = config.interval
        self.max_interval = config.max_interval

        if config.backoff is not None:
            self.backoff: float = config.backoff
        else:
            self.backoff = 1

        self._retries = 0

    def reset(self) -> None:
        self._retries = 0

    def next(self) -> timedelta:
        next = self.interval * self.backoff**self._retries
        if self.max_interval is not None and next > self.max_interval:
            next = self.max_interval
        self._retries += 1
        return next


@validated_dataclass(kw_only=True, frozen=True)
class ConnectionParameters(ComponentParameters):
    reconnect: ConnectionReconnect


@validated_dataclass(kw_only=True, frozen=True)
class ConnectionContext(ComponentContext):
    path: ConnectionPath


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


class Connection(Component[ConnectionParameters, ConnectionContext], ABC):
    def __init__(
        self,
        parameters: ConnectionParameters,
        context: ConnectionContext,
    ) -> None:
        super().__init__(parameters, context)
        self._state = ConnectionState.DISCONNECTED
        self._last_message_sent: Message | None = None
        self._last_message_received: Message | None = None
        self._reconnect = ReconnectScheduler(self.parameters.reconnect)
        self._message_queue: AsyncQueue[Message] = AsyncQueue()

    @property
    def path(self) -> ConnectionPath:
        return self.context.path

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED

    @property
    def last_message_sent(self) -> Message | None:
        return self._last_message_sent

    @property
    def last_message_received(self) -> Message | None:
        return self._last_message_received

    @property
    async def message_stream(self) -> AsyncIterable[Message]:
        while True:
            yield await self.get_next_message()

    async def get_next_message(self) -> Message:
        return await self._message_queue.get()

    def emit_message(self, message: Message) -> Message:
        self._message_queue.put_nowait(message)
        return message

    async def try_connect(self) -> bool:
        pass

    async def try_disconnect(self) -> None:
        pass

    async def send_data(self, data: bytes) -> None:
        raise NotImplementedError()

    async def receive_data(self) -> bytes:
        raise NotImplementedError()

    async def connect(self) -> bool:
        if self._state == ConnectionState.CONNECTED:
            return True

        self.logger.info("Connecting...")

        self._state = ConnectionState.CONNECTING
        if await self.try_connect():
            self._state = ConnectionState.CONNECTED
            self.emit_event(
                ConnectedEvent(
                    path=LocalConnectionPath(self.context.path.name),
                )
            )
            self.logger.info("Connected successfully.")
        else:
            self._state = ConnectionState.DISCONNECTED
            self.logger.error("Failed to connect.")

        return self.connected

    async def send(self, data: bytes) -> Message:
        try:
            await self.send_data(data)
        except Exception:
            await self.disconnect()
            raise

        message = Message(
            connection_id=self.context.id,
            direction=MessageDirection.SEND,
            content=data,
        )

        self.emit_message(message)
        self.emit_event(
            MessageSentEvent(
                path=LocalConnectionPath(self.context.path.name),
                message=message,
            )
        )

        self._last_message_sent = message

        return message

    async def receive(self) -> Message:
        data = await self.receive_data()
        message = Message(
            connection_id=self.context.id,
            direction=MessageDirection.RECEIVE,
            content=data,
        )

        self.emit_message(message)
        self.emit_event(
            MessageReceivedEvent(
                path=LocalConnectionPath(self.context.path.name),
                message=message,
            )
        )

        self._last_message_received = message
        return message

    async def disconnect(self) -> None:
        if self._state == ConnectionState.DISCONNECTED:
            return

        self.logger.info("Disconnecting...")

        try:
            await self.try_disconnect()
        finally:
            self._state = ConnectionState.DISCONNECTED
            self.emit_event(
                DisconnectedEvent(
                    path=LocalConnectionPath(self.context.path.name),
                )
            )

            self.logger.info("Disconnected.")

    async def _tasklet_run(self) -> None:
        async def process_update() -> None:
            while True:
                while not await self.connect():
                    self.emit_alert("error", "connection-attempt-failed")
                    seconds = self._reconnect.next().total_seconds()
                    self.logger.info(f"Reconnecting in {seconds:g} seconds...")
                    await asyncio.sleep(seconds)

        self._reconnect.reset()

        while self._state == ConnectionState.CONNECTED:
            await self.receive()

        await asyncio.gather(
            super()._tasklet_run(),
            process_update(),
        )

    async def _tasklet_stop(self) -> None:
        await super()._tasklet_stop()

        await self.try_disconnect()


class ConnectionReference(Reference[ReferencedConnectionHandle]):
    @property
    def path(self) -> LocalConnectionPath:
        return LocalConnectionPath(self.name)
