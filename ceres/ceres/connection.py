import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Any

from pydantic import validator
from pydantic.dataclasses import dataclass as validated_dataclass

from .address import LocalComponentAddress
from .component import Component, ComponentContext, ComponentParameters
from .events import (
    ConnectedEvent,
    DisconnectedEvent,
    MessageReceivedEvent,
    MessageSentEvent,
)
from .internal.utilities import validate_positive_timedelta
from .message import Message, MessageDirection
from .stream import Stream, StreamView


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
    pass


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


@dataclass(kw_only=True)
class ConnectionInternal:
    state: ConnectionState
    last_message_sent: Message | None
    last_message_received: Message | None
    reconnect: ReconnectScheduler
    message_stream: Stream[Message]


class Connection(Component[ConnectionParameters, ConnectionContext], ABC):
    def __init__(
        self,
        parameters: ConnectionParameters,
        context: ConnectionContext,
    ) -> None:
        super().__init__(parameters, context)
        self.__connection_internal__ = ConnectionInternal(
            state=ConnectionState.DISCONNECTED,
            last_message_sent=None,
            last_message_received=None,
            reconnect=ReconnectScheduler(self.parameters.reconnect),
            message_stream=Stream(),
        )

    @property
    def state(self) -> ConnectionState:
        return self.__connection_internal__.state

    @property
    def connected(self) -> bool:
        return self.state == ConnectionState.CONNECTED

    @property
    def last_message_sent(self) -> Message | None:
        return self.__connection_internal__.last_message_sent

    @property
    def last_message_received(self) -> Message | None:
        return self.__connection_internal__.last_message_received

    @property
    def message_stream(self) -> StreamView[Message]:
        return self.__connection_internal__.message_stream.view()

    def emit_message(self, message: Message) -> Message:
        self.__connection_internal__.message_stream.put(message)
        return message

    @abstractmethod
    async def try_connect(self) -> bool:
        ...

    @abstractmethod
    async def try_disconnect(self) -> None:
        ...

    @abstractmethod
    async def send_data(self, data: bytes) -> None:
        ...

    @abstractmethod
    async def receive_data(self) -> bytes:
        ...

    async def connect(self) -> bool:
        if self.state == ConnectionState.CONNECTED:
            return True

        self.logger.info("Connecting...")

        self.__connection_internal__.state = ConnectionState.CONNECTING
        if await self.try_connect():
            self.__connection_internal__.state = ConnectionState.CONNECTED
            self.emit_event(
                ConnectedEvent(
                    address=LocalComponentAddress(self.context.address.name),
                )
            )
            self.logger.info("Connected successfully.")
        else:
            self.__connection_internal__.state = ConnectionState.DISCONNECTED
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
                address=LocalComponentAddress(self.context.address.name),
                message=message,
            )
        )

        self.__connection_internal__.last_message_sent = message

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
                address=LocalComponentAddress(self.context.address.name),
                message=message,
            )
        )

        self.__connection_internal__.last_message_received = message
        return message

    async def disconnect(self) -> None:
        if self.state == ConnectionState.DISCONNECTED:
            return

        self.logger.info("Disconnecting...")

        try:
            await self.try_disconnect()
        finally:
            self.__connection_internal__.state = ConnectionState.DISCONNECTED
            self.emit_event(
                DisconnectedEvent(
                    address=LocalComponentAddress(self.context.address.name),
                )
            )

            self.logger.info("Disconnected.")

    async def _tasklet_run(self) -> None:
        async def process_update() -> None:
            while True:
                while not await self.connect():
                    self.emit_alert("error", "connection-attempt-failed")
                    seconds = self.__connection_internal__.reconnect.next().total_seconds()
                    self.logger.info(f"Reconnecting in {seconds:g} seconds...")
                    await asyncio.sleep(seconds)

        self.__connection_internal__.reconnect.reset()

        while self.__connection_internal__.state == ConnectionState.CONNECTED:
            await self.receive()

        await asyncio.gather(
            super()._tasklet_run(),
            process_update(),
        )

    async def _tasklet_stop(self) -> None:
        await super()._tasklet_stop()

        await self.try_disconnect()
